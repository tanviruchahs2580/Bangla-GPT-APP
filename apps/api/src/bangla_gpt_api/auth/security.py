import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import User

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
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
