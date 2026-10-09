import hashlib
import hmac
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
    """
    expires_delta = timedelta(minutes=settings.jwt_expire_minutes if minutes is None else minutes)
    payload: dict[str, object] = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.now(UTC) + expires_delta,
        "iat": issued_at if issued_at is not None else int(time.time()),
        "jti": jti or uuid4().hex,  # unique id per token for revocation
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, *, settings: Settings) -> dict:
    """Raises jwt.PyJWTError subclasses on invalid/expired tokens."""
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
