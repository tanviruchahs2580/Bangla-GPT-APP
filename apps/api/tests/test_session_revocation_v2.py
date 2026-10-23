"""S-011/S-012/F-142: session revocation, TOTP account throttle, erasure
re-auth.

Three audit gaps, closed together because they chain into one attack: a
bearer token lived its full 60 minutes with no kill switch (S-011), TOTP
guessing had no per-ACCOUNT bound (S-012), and irreversible account
erasure rode on that unkillable token alone (F-142).
"""

import time

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.auth.mfa import _hotp
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

SECRET = "test-secret-0123456789abcdef0123456789"
PASSWORD = "StrongPass123!"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/sessions.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str) -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert res.status_code == 201, res.text


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _me(client: TestClient, headers: dict) -> int:
    return client.get("/users/me", headers=headers).status_code


# --- S-011: per-session and account-wide revocation ------------------------


def test_logout_revokes_only_the_presented_token(client: TestClient) -> None:
    _register(client, "two-sessions@example.com")
    first = _login(client, "two-sessions@example.com")
    second = _login(client, "two-sessions@example.com")

    out = client.post("/auth/logout", headers=first)
    assert out.status_code == 204

    # the logged-out token dies at once; the sibling session is untouched
    assert _me(client, first) == 401
    assert _me(client, second) == 200


def test_sessions_revoke_kills_every_token(client: TestClient) -> None:
    _register(client, "everywhere@example.com")
    a = _login(client, "everywhere@example.com")
    b = _login(client, "everywhere@example.com")

    # The F-05 epoch comparison is integer-second: tokens minted in the SAME
    # second as the stamp intentionally survive (see deps.py - a sub-second
    # boundary is not expressible with integer iat, and change-password must
    # return a usable token). Cross that boundary deterministically.
    time.sleep(1.1)
    res = client.post("/users/me/sessions/revoke", headers=a)
    assert res.status_code == 204

    # DB-backed epoch stamp: both sessions fail on their next request
    assert _me(client, a) == 401
    assert _me(client, b) == 401

    # a fresh login still works — the account is not deleted, just signed out
    fresh = _login(client, "everywhere@example.com")
    assert _me(client, fresh) == 200


def test_logout_requires_a_live_token(client: TestClient) -> None:
    _register(client, "anon-logout@example.com")
    assert client.post("/auth/logout").status_code == 401


# --- F-142: erasure re-authenticates ----------------------------------------


def test_delete_me_requires_the_current_password(client: TestClient) -> None:
    _register(client, "erase-me@example.com")
    headers = _login(client, "erase-me@example.com")

    # no body, wrong password: both refused with the same coded 401, so the
    # response is not a password oracle either way
    no_body = client.request("DELETE", "/users/me", headers=headers)
    wrong = client.request("DELETE", "/users/me", headers=headers, json={"password": "not-the-password"})
    assert no_body.status_code == 401
    assert no_body.json()["detail"]["code"] == "bad_current_password"
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "bad_current_password"

    # the account is still alive after both refusals
    assert _me(client, headers) == 200

    gone = client.request("DELETE", "/users/me", headers=headers, json={"password": PASSWORD})
    assert gone.status_code == 204
    assert _me(client, headers) == 401


# --- S-012: per-account TOTP throttle ---------------------------------------


def _enable_mfa(client: TestClient, headers: dict) -> str:
    enroll = client.post("/auth/mfa/enroll", headers=headers)
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]
    code = _hotp(secret, int(time.time()) // 30)
    ok = client.post("/auth/mfa/verify", json={"secret": secret, "code": code}, headers=headers)
    assert ok.status_code == 200
    return secret


def test_mfa_challenge_locks_the_account_after_ten_failures(tmp_path) -> None:
    # The per-IP rule (5/min) fires before the account counter at default
    # limits; raise it so this test exercises the ACCOUNT-level bound that
    # defeats IP rotation.
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/mfa-throttle.db",
        jwt_secret=SECRET,
        rate_limit_rules={"/auth/mfa/challenge": (1000, "ip")},
    )
    client = TestClient(create_app(settings))
    _register(client, "throttle@example.com")
    headers = _login(client, "throttle@example.com")
    secret = _enable_mfa(client, headers)

    step = client.post("/auth/login", json={"email": "throttle@example.com", "password": PASSWORD})
    assert step.status_code == 202
    mfa_token = step.json()["access_token"]

    def challenge(code: str):
        return client.post("/auth/mfa/challenge", json={"mfa_token": mfa_token, "code": code})

    # ten wrong codes: 401 bad_mfa_code every time (same body — no oracle)
    for _ in range(10):
        res = challenge("000000")
        assert res.status_code == 401
        assert res.json()["detail"]["code"] == "bad_mfa_code"

    # the account is now locked even for the CORRECT code: the lock is
    # checked before the code, so guessing cannot continue from another IP
    right_code = _hotp(secret, int(time.time()) // 30)
    locked = challenge(right_code)
    assert locked.status_code == 429
    assert locked.json()["detail"]["code"] == "mfa_locked"
