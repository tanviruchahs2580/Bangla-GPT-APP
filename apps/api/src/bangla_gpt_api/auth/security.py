import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import User
from bangla_gpt_api.services.breached_passwords import BREACHED_PASSWORDS, fold_variants

# OWASP Password Storage Cheat Sheet (fetched 2026-10-09): "Argon2id with a
# minimum configuration of 19 MiB of memory, an iteration count of 2, and 1
# degree of parallelism." PBKDF2-HMAC-SHA256, which this codebase used before,
# is only the fallback recommendation at 600,000 iterations; the older 200,000
# iterations were below even that floor.
_ARGON2 = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)

#: A real Argon2id hash of a value nobody knows, verified against on the
#: "no such user" login path so that path costs the same as a real one
#: (F-057). Generated lazily: hashing at import time would add ~50ms to
#: every process start, including alembic and the CLI.
_DECOY_HASH: str | None = None

#: The most-used passwords in the world. Checked case-insensitively after
#: leetspeak folding (see ``services/breached_passwords.fold_variants``),
#: because "P@ssw0rd1" is the same guess as "password1" (F-072). This is the
#: hand-curated obvious set; the embedded breach corpus lives in
#: ``services/breached_passwords.BREACHED_PASSWORDS`` (AUD-B-06) and
#: ``is_common_password`` checks both.
COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "passw0rd",
        "p@ssw0rd",
        "p@ssword",
        "123456",
        "12345678",
        "123456789",
        "1234567890",
        "12345678901",
        "qwerty",
        "qwerty123",
        "abc123",
        "111111",
        "000000",
        "123123",
        "admin",
        "admin123",
        "administrator",
        "letmein",
        "welcome",
        "welcome1",
        "monkey",
        "dragon",
        "iloveyou",
        "sunshine",
        "princess",
        "football",
        "baseball",
        "superman",
        "trustno1",
        "starwars",
        "whatever",
        "freedom",
        "computer",
        "internet",
        "bangladesh",
        "bangla",
        "dhaka",
        "bangladeshi",
        "student",
        "teacher",
        "school",
        "secret",
        "login",
        "root",
        "toor",
        "changeme",
        "default",
        "guest",
        "test",
        "test123",
        "user",
        "user123",
    }
)


def _variants(password: str) -> set[str]:
    """The shapes a guesser would actually try for this candidate.

    AUD-B-06: the transformation itself now lives in
    ``services/breached_passwords.fold_variants`` so the small blocklist here
    and the embedded breached corpus cannot drift apart in how they read a
    candidate. This alias keeps the module's historical call sites (and its
    tests) working unchanged.
    """
    return fold_variants(password)


def is_common_password(password: str) -> bool:
    """True when the password is a well-known guess (F-072/AUD-B-06).

    Three layers, all offline:

    1. ``COMMON_PASSWORDS`` -- the hand-curated obvious choices.
    2. ``BREACHED_PASSWORDS`` -- the embedded top of the public breach lists
       (AUD-B-06); NIST SP 800-63B §3.1.1.2 requires a breached-value check
       and this repository cannot call a network service from registration.
    3. Structure rules for the guesses no word list holds: "aaaaaaaa",
       "abababab", "00000000" (NIST's repetitive-character check).
    """
    if not (password or "").strip():
        return True
    if _variants(password) & (COMMON_PASSWORDS | BREACHED_PASSWORDS):
        return True
    # Structure rules, covering the guesses no word list holds:
    # "aaaaaaaa", "abababab", "00000000".
    if len(set(password)) <= 3:
        return True
    return any(
        len(password) >= unit * 2
        and len(password) % unit == 0
        and password[:unit] * (len(password) // unit) == password
        for unit in (2, 3, 4, 6, 8)
    )


def _burn_password_check(password: str) -> None:
    """Spend the same CPU an Argon2id verification would have spent.

    Called on the login path when no account matched, so the response time
    does not disclose whether the address is registered.
    """
    global _DECOY_HASH
    if _DECOY_HASH is None:
        _DECOY_HASH = _ARGON2.hash(secrets.token_urlsafe(32))
    verify_password(password, _DECOY_HASH)


def hash_password(password: str) -> str:
    """Hash a password with Argon2id at the OWASP parameters."""
    return _ARGON2.hash(password)


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against an Argon2id or legacy pbkdf2_sha256 hash."""
    if stored.startswith("$argon2"):
        try:
            _ARGON2.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False
        return True
    return _verify_legacy_pbkdf2(password, stored)


def needs_rehash(stored: str) -> bool:
    """True when a *successfully verified* hash should be upgraded in place.

    Any legacy hash needs upgrading; an Argon2id hash needs it when it was
    produced with weaker parameters than the current policy. Callers must only
    invoke this after ``verify_password`` returned True.
    """
    if not stored.startswith("$argon2"):
        return True
    return _ARGON2.check_needs_rehash(stored)


def _verify_legacy_pbkdf2(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
    ).hex()
    return hmac.compare_digest(candidate, expected)


#: Claims this module owns. ``extra_claims`` may add anything else
#: (``imp``, ``mfa``, …) but never one of these.
RESERVED_CLAIMS = frozenset({"sub", "role", "iss", "aud", "exp", "iat", "jti"})

#: Token-purpose marker (B-02). ``get_current_user`` refuses ``refresh``
#: tokens: a long-lived credential that only exists to mint access tokens
#: must never be usable as an API credential itself.
ACCESS_TOKEN_TYP = "access"  # noqa: S105 - a token type string, not a credential
REFRESH_TOKEN_TYP = "refresh"  # noqa: S105 - a token type string, not a credential


def create_access_token(
    user: User,
    *,
    settings: Settings,
    minutes: int | None = None,
    extra_claims: dict[str, object] | None = None,
    jti: str | None = None,
    issued_at: int | None = None,
) -> str:
    """Create a JWT access token with a unique ``jti`` and the ``iat`` epoch.

    Unlike the legacy flow that only set ``jti`` for impersonation, this
    version embeds a ``jti`` (JWT ID) on *all* access tokens so every token
    can be individually revoked before expiry via the shared token deny-list.
    The ``iat`` claim powers the F-05 token epoch: when a user's
    ``sessions_invalidated_at`` is set (password change/reset), every token
    issued in an earlier second is refused by ``get_current_user``. The
    boundary is second-precision (PyJWT rejects future ``iat``), so
    same-second mints stay valid and the replacement token is minted
    naturally.

    ``extra_claims`` is applied FIRST and the reserved claims are written
    afterwards. The previous order (``payload.update(extra_claims)`` last)
    meant a caller passing ``{"role": "admin"}`` produced a token whose
    authorization came from the call site rather than from the database —
    every current call site passes only ``imp``/``mfa``, so the exposure was
    latent rather than exploited, but it is exactly the kind of thing a new
    caller silently inherits.
    """
    expires_delta = timedelta(minutes=settings.jwt_expire_minutes if minutes is None else minutes)
    payload: dict[str, object] = dict(extra_claims or {})
    payload.update(
        {
            "sub": str(user.id),
            "role": user.role,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "exp": datetime.now(UTC) + expires_delta,
            "iat": issued_at if issued_at is not None else int(time.time()),
            "jti": jti or uuid4().hex,  # unique id per token for revocation
            "typ": ACCESS_TOKEN_TYP,
        }
    )
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(
    user: User,
    *,
    settings: Settings,
    family: str | None = None,
    jti: str | None = None,
    issued_at: int | None = None,
    days: int | None = None,
) -> str:
    """Mint a refresh token (B-02): long-lived, single-use, family-bound.

    The token carries no authorization claims (no ``role``): it cannot be
    used as an API credential (``get_current_user`` refuses ``typ=refresh``)
    and the access token it mints gets its role from the CURRENT database
    row, so a role changed after the login is reflected on the next refresh
    instead of being frozen for the refresh token's lifetime.

    ``family`` is the login's rotation lineage. ``POST /auth/refresh`` claims
    the token's ``jti`` atomically (SET NX) and issues a successor with the
    same family; presenting an already-rotated token revokes the whole family
    — the standard stolen-refresh-token response: the thief and the victim
    are both logged out, and only a fresh login gets back in.

    ``days`` overrides the configured lifetime (tests, and a future
    remember-me policy); the default is ``jwt_refresh_expire_days``.
    """
    expires_delta = timedelta(days=settings.jwt_refresh_expire_days if days is None else days)
    payload: dict[str, object] = {
        "sub": str(user.id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": datetime.now(UTC) + expires_delta,
        "iat": issued_at if issued_at is not None else int(time.time()),
        "jti": jti or uuid4().hex,
        "typ": REFRESH_TOKEN_TYP,
        "fam": family or uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, *, settings: Settings) -> dict:
    """Raises jwt.PyJWTError subclasses on invalid/expired tokens.

    ``iss`` and ``aud`` are required: a token without them (including every
    token minted before SEC-03) is refused, which forces a one-time re-login
    rather than silently accepting unbound tokens.
    """
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )
