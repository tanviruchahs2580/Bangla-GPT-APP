"""AUTH-001: TOTP multi-factor authentication (stdlib RFC 6238).

Covers the RFC test vector, the full enroll→verify→login→challenge→disable
lifecycle, step-up token isolation (mfa tokens never work as API tokens),
and backward compatibility (accounts without MFA see zero change).
"""

import time

from fastapi.testclient import TestClient

from bangla_gpt_api.auth.mfa import _hotp, new_secret, otpauth_uri, verify_code
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

SECRET = "test-secret-0123456789abcdef0123456789"
PASSWORD = "StrongPass123!"

# RFC 6238 Appendix B, SHA-1: ASCII "12345678901234567890" at T=59 → 94287082.
RFC_SECRET_B32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def _settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/mfa.db",
        jwt_secret=SECRET,
    )


def _register_login(client: TestClient, email: str = "mfa@example.com") -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Mfa",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _current_code(secret: str) -> str:
    return _hotp(secret, int(time.time()) // 30)


def test_rfc6238_vector() -> None:
    assert _hotp(RFC_SECRET_B32, 1) == "287082"
    assert verify_code(RFC_SECRET_B32, "287082", now=59) is True
    assert verify_code(RFC_SECRET_B32, "287083", now=59) is False
    assert verify_code(RFC_SECRET_B32, "28708a", now=59) is False
    assert verify_code(RFC_SECRET_B32, "28708", now=59) is False


def test_secret_and_uri_shape() -> None:
    secret = new_secret()
    assert len(secret) == 32
    uri = otpauth_uri(secret, "Kid@Example.com")
    assert uri.startswith("otpauth://totp/Bangla GPT:kid@example.com?secret=")
    assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri


def test_full_mfa_lifecycle(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _register_login(client)

    # 1. enroll returns a secret but enables nothing yet
    enroll = client.post("/auth/mfa/enroll", headers=headers)
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]
    assert len(secret) == 32
    still_plain = client.post(
        "/auth/login", json={"email": "mfa@example.com", "password": PASSWORD}
    )
    assert still_plain.status_code == 200
    assert still_plain.json()["token_type"] == "bearer"

    # 2. wrong code rejected; right code enables
    bad = client.post(
        "/auth/mfa/verify", json={"secret": secret, "code": "000000"}, headers=headers
    )
    assert bad.status_code == 401
    good = client.post(
        "/auth/mfa/verify", json={"secret": secret, "code": _current_code(secret)}, headers=headers
    )
    assert good.status_code == 200
    assert good.json() == {"enabled": True}
    dup = client.post(
        "/auth/mfa/verify", json={"secret": secret, "code": _current_code(secret)}, headers=headers
    )
    assert dup.status_code == 409

    # 3. login now demands step-up
    step = client.post("/auth/login", json={"email": "mfa@example.com", "password": PASSWORD})
    assert step.status_code == 202
    assert step.json()["token_type"] == "mfa"
    mfa_token = step.json()["access_token"]

    # 4. the step-up token is useless as an API token
    me = client.get("/users/me", headers={"Authorization": f"Bearer {mfa_token}"})
    assert me.status_code == 401

    # 5. challenge: wrong code fails, right code yields a bearer token
    bad_ch = client.post("/auth/mfa/challenge", json={"mfa_token": mfa_token, "code": "000000"})
    assert bad_ch.status_code == 401
    ok_ch = client.post(
        "/auth/mfa/challenge",
        json={"mfa_token": mfa_token, "code": _current_code(secret)},
    )
    assert ok_ch.status_code == 200
    assert ok_ch.json()["token_type"] == "bearer"
    bearer = {"Authorization": f"Bearer {ok_ch.json()['access_token']}"}
    assert client.get("/users/me", headers=bearer).status_code == 200

    # 6. a normal bearer token is not a step-up token
    not_step = client.post(
        "/auth/mfa/challenge",
        json={"mfa_token": ok_ch.json()["access_token"], "code": _current_code(secret)},
    )
    assert not_step.status_code == 401

    # 7. disable requires the password, then login is plain again
    bad_dis = client.post("/auth/mfa/disable", json={"password": "wrong"}, headers=bearer)
    assert bad_dis.status_code == 401
    dis = client.post("/auth/mfa/disable", json={"password": PASSWORD}, headers=bearer)
    assert dis.status_code == 200
    assert dis.json() == {"disabled": True}
    plain = client.post("/auth/login", json={"email": "mfa@example.com", "password": PASSWORD})
    assert plain.status_code == 200
    assert plain.json()["token_type"] == "bearer"
