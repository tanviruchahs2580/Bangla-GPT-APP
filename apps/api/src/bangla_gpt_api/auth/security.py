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
#: leetspeak folding, because "P@ssw0rd1" is the same guess as "password1"
#: (F-072). This is a floor, not a replacement for a breach corpus: it
#: exists so the obvious choices cannot be registered at all.
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

_LEET = str.maketrans(
    {"@": "a", "0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "$": "s"}
)


def _variants(password: str) -> set[str]:
    """The shapes a guesser would actually try for this candidate.

    Both the plain lowercase form and the leet-folded form are kept. Either
    transformation on its own makes the blocklist silently useless: folding
    turns "12345678" into "l2eas6t8", which matches nothing in any word list,
    and collapsing repeated characters turns "password" into "pasword", which
    also matches nothing.
    """
    lowered = (password or "").strip().lower()
    if not lowered:
        return set()
    out: set[str] = set()
    for form in (lowered, lowered.translate(_LEET)):
        out.add(form)
        stripped = form.rstrip("0123456789")
        if stripped:
            out.add(stripped)
    return out


def is_common_password(password: str) -> bool:
    """True when the password is a well-known guess (F-072)."""
    if not (password or "").strip():
        return True
    if _variants(password) & COMMON_PASSWORDS:
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


def reject_common_password(password: str) -> None:
    """Raise the standard coded 400 for a well-known guess.

    One place for the rule so registration, reset and change-password cannot
    drift apart: a blocklist applied on registration alone is bypassed the
    moment a user resets to "12345678".
    """
    if is_common_password(password):
        raise CommonPasswordError


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


class CommonPasswordError(ValueError):
    """The candidate is a well-known guess (F-072)."""


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
        }
    )
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
