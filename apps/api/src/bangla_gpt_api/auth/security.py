import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

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
) -> str:
    expires_delta = timedelta(minutes=settings.jwt_expire_minutes if minutes is None else minutes)
    payload: dict[str, object] = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.now(UTC) + expires_delta,
    }
    if jti is not None:
        # S5.10: impersonation tokens carry an id so a live session can be
        # revoked before its (short) expiry through the shared cache deny-list.
        payload["jti"] = jti
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, *, settings: Settings) -> dict:
    """Raises jwt.PyJWTError subclasses on invalid/expired tokens."""
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
