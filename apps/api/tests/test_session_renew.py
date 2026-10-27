"""B-02: ``POST /auth/renew`` slides a session forward, fail-securely.

The 60-minute JWT hard-expired into a mid-task logout with no way back: a
student 35 minutes into a quiz, a teacher mid bulk-import. The backend
half of the fix is a renewal endpoint with a deliberately narrow contract:

* renew while the presented token still verifies -> a fresh jti + a full
  window (the web client renews proactively; the old token dies of
  natural causes, so an in-flight request racing the renewal is safe);
* an EXPIRED token cannot renew -- fail-secure, no grace window, no
  replay surface;
* MFA step-up tokens are already refused upstream (CurrentUser);
* impersonation tokens must NOT renew (the 15-minute window is that
  design's safety bound).
"""

import time

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.auth.security import decode_token
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "renew"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


def _register_and_login(client: TestClient, email: str, role: str = "student") -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "User", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    assert client.post("/auth/register", json=payload).status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _claims(client: TestClient, token: str) -> dict:
    return decode_token(token.replace("Bearer ", ""), settings=client.app.state.ctx.settings)


def test_renew_returns_a_fresh_token_that_works(client: TestClient) -> None:
    headers = _register_and_login(client, "renew@example.com")
    old_exp = _claims(client, headers["Authorization"])["exp"]

    res = client.post("/auth/renew", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["access_token"]
    new_exp = _claims(client, "Bearer " + body["access_token"])["exp"]
    # a full window from NOW: within seconds of the default 60 minutes, and
    # not a shrinking leftover of the presented token's lifetime. Same-second
    # renewals legitimately keep the old wall-clock second (>=).
    assert new_exp - time.time() >= 55 * 60
    assert new_exp >= old_exp
    # and a brand-new jti: the deny-list contract keeps per-token identity
    new_jti = _claims(client, "Bearer " + body["access_token"])["jti"]
    assert new_jti != _claims(client, headers["Authorization"])["jti"]

    # the fresh token authenticates the caller immediately
    me = client.get("/users/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200


def test_expired_token_cannot_renew(client: TestClient) -> None:
    headers = _register_and_login(client, "expired@example.com")
    user_id = client.get("/users/me", headers=headers).json()["user_id"]

    settings = client.app.state.ctx.settings
    expired = pyjwt.encode(
        {
            "sub": str(user_id),
            "role": "student",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "exp": int(time.time()) - 60,
            "iat": int(time.time()) - 120,
            "jti": "expiredjti0123456789",
        },
        SECRET,
        algorithm="HS256",
    )
    res = client.post("/auth/renew", headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401, res.text


def test_impersonation_token_cannot_renew(client: TestClient) -> None:
    # platform admin impersonates a student; the 15-minute window is the
    # safety bound of that feature and must not be extendable
    student = _register_and_login(client, "victim@example.com")
    user_id = client.get("/users/me", headers=student).json()["user_id"]
    # the platform admin is boot-seeded (registration cannot mint admins)
    admin_login = client.post(
        "/auth/login", json={"email": "root@example.com", "password": PASSWORD}
    )
    assert admin_login.status_code == 200, admin_login.text
    admin = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    res = client.post(
        f"/admin/users/{user_id}/impersonate",
        json={"reason": "session-renew contract pin"},
        headers=admin,
    )
    assert res.status_code == 200, res.text
    imp_token = res.json()["access_token"]

    renewed = client.post("/auth/renew", headers={"Authorization": f"Bearer {imp_token}"})
    assert renewed.status_code == 403, renewed.text
    assert renewed.json()["detail"]["code"] == "renew_unavailable"
    # the original impersonation token still works for normal routes
    me = client.get("/users/me", headers={"Authorization": f"Bearer {imp_token}"})
    assert me.status_code == 200
