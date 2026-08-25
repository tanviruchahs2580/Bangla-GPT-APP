from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest

from bangla_gpt_api.auth.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from bangla_gpt_api.config import Settings


def test_password_hash_roundtrip() -> None:
    stored = hash_password("correct-horse-battery")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("correct-horse-battery", stored)
    assert not verify_password("wrong-password", stored)


def test_verify_password_rejects_corrupt_stored_value() -> None:
    assert not verify_password("x", "not-a-valid-hash")
    assert not verify_password("x", "md5$1$aa$bb")


def test_token_roundtrip_carries_identity() -> None:
    settings = Settings(jwt_secret="unit-secret-0123456789abcdef0123456789")

    class FakeUser:
        id = 7
        role = "student"

    token = create_access_token(FakeUser(), settings=settings, minutes=5)
    payload = decode_token(token, settings=settings)
    assert payload["sub"] == "7"
    assert payload["role"] == "student"


def test_decode_rejects_wrong_secret_and_expired_token() -> None:
    settings = Settings(jwt_secret="unit-secret-0123456789abcdef0123456789")

    class FakeUser:
        id = 7
        role = "teacher"

    with pytest.raises(pyjwt.PyJWTError):
        decode_token(
            create_access_token(
                FakeUser(), settings=Settings(jwt_secret="other-secret-0123456789abcdef0123")
            ),
            settings=settings,
        )

    expired = pyjwt.encode(
        {"sub": "7", "role": "teacher", "exp": datetime.now(UTC) - timedelta(seconds=1)},
        "unit-secret-0123456789abcdef0123456789",
        algorithm="HS256",
    )
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(expired, settings=settings)
