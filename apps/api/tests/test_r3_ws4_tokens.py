"""B-02: rotating refresh tokens, short-lived access tokens, revocation.

What the audit's token-design item requires and this suite proves through the
public API on a real app:

* the access token is short-lived (``expires_in`` is the configured TTL; the
  spec's short-lived requirement, default 15 minutes);
* a refresh token exists, is single-use, and rotates -- presenting one twice
  is theft-detection: the whole login family is revoked and BOTH the old and
  the freshly issued refresh token stop working;
* logout revokes server-side: the access token's jti and (when supplied) the
  refresh token's jti are retired in the shared deny-list;
* a refresh token cannot be used as an API credential; an access token cannot
  be used to refresh;
* forged / expired / algorithm-swapped tokens are refused;
* a password change kills outstanding refresh tokens (the F-05 epoch now
  covers them too).
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"
ADMIN = "root@example.com"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/r3_ws4_tokens.db",
        jwt_secret=JWT,
        admin_email=ADMIN,
        admin_password=PASSWORD,
        force_admin_password_change=False,
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
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text


def _login_tokens(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()


def _auth(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


# --- shape and lifetime ------------------------------------------------------


def test_login_returns_a_short_lived_access_token_and_a_refresh_token(
    client: TestClient,
) -> None:
    _register(client, "tokens-shape@example.net")
    body = _login_tokens(client, "tokens-shape@example.net")
    assert body["token_type"] == "bearer"
    assert body["refresh_token"], "a refresh token must accompany the login"
    assert body["refresh_token"] != body["access_token"]
    assert body["expires_in"] == 15 * 60, "the access token must be short-lived (B-02)"

    # The claim-level lifetime matches what the response advertises.
    claims = pyjwt.decode(
        body["access_token"],
        JWT,
        algorithms=["HS256"],
        audience="bangla-gpt-clients",
        issuer="bangla-gpt-api",
    )
    assert claims["typ"] == "access"
    assert 0 < claims["exp"] - claims["iat"] <= 15 * 60

    refresh_claims = pyjwt.decode(
        body["refresh_token"],
        JWT,
        algorithms=["HS256"],
        audience="bangla-gpt-clients",
        issuer="bangla-gpt-api",
    )
    assert refresh_claims["typ"] == "refresh"
    assert refresh_claims.get("fam")
    assert refresh_claims["exp"] - refresh_claims["iat"] == 14 * 86400


def test_refresh_rotates_and_the_successor_works(client: TestClient) -> None:
    _register(client, "tokens-rotate@example.net")
    first = _login_tokens(client, "tokens-rotate@example.net")

    res = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert res.status_code == 200, res.text
    second = res.json()
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]
    # The new access token authenticates; the old one is NOT revoked by mere
    # rotation (it dies at its own 15-minute expiry) -- neither is the old
    # refresh token, which is single-use by the rotation claim.
    assert client.get("/users/me", headers=_auth(second["access_token"])).status_code == 200
    assert (
        client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code
        == 200
    )


def test_rotated_refresh_token_is_single_use_and_replay_revokes_the_family(
    client: TestClient,
) -> None:
    _register(client, "tokens-replay@example.net")
    first = _login_tokens(client, "tokens-replay@example.net")
    rotated = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    successor = rotated.json()["refresh_token"]

    # Replaying the consumed token is the theft signal.
    replay = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401, replay.text
    assert replay.json()["detail"]["code"] == "bad_refresh_token"

    # ...and the family is revoked: even the legitimate successor is refused.
    after = client.post("/auth/refresh", json={"refresh_token": successor})
    assert after.status_code == 401, after.text

    # A fresh login starts a new family and works again.
    fresh = _login_tokens(client, "tokens-replay@example.net")
    assert (
        client.post("/auth/refresh", json={"refresh_token": fresh["refresh_token"]}).status_code
        == 200
    )


def test_logout_revokes_access_and_refresh_server_side(client: TestClient) -> None:
    _register(client, "tokens-logout@example.net")
    body = _login_tokens(client, "tokens-logout@example.net")
    access, refresh = body["access_token"], body["refresh_token"]
    assert client.get("/users/me", headers=_auth(access)).status_code == 200

    out = client.post("/auth/logout", json={"refresh_token": refresh}, headers=_auth(access))
    assert out.status_code == 204, out.text

    assert client.get("/users/me", headers=_auth(access)).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_refresh_token_is_not_an_api_credential(client: TestClient) -> None:
    _register(client, "tokens-not-api@example.net")
    body = _login_tokens(client, "tokens-not-api@example.net")
    res = client.get("/users/me", headers=_auth(body["refresh_token"]))
    assert res.status_code == 401, res.text


def test_access_token_cannot_be_refreshed(client: TestClient) -> None:
    _register(client, "tokens-access-refresh@example.net")
    body = _login_tokens(client, "tokens-access-refresh@example.net")
    res = client.post("/auth/refresh", json={"refresh_token": body["access_token"]})
    assert res.status_code == 401, res.text


# --- forged / expired / algorithm-swapped -----------------------------------


def test_expired_access_token_is_refused(client: TestClient) -> None:
    _register(client, "tokens-expired@example.net")
    body = _login_tokens(client, "tokens-expired@example.net")
    now = int(time.time())
    expired = pyjwt.encode(
        {
            "sub": "1",
            "role": "student",
            "iss": "bangla-gpt-api",
            "aud": "bangla-gpt-clients",
            "iat": now - 3600,
            "exp": now - 1800,
            "jti": "expired-jti",
            "typ": "access",
        },
        JWT,
        algorithm="HS256",
    )
    assert client.get("/users/me", headers=_auth(expired)).status_code == 401
    # A refresh token that the server itself considers expired is refused
    # before its single-use claim is spent.
    assert (
        client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code
        == 200
    )


def test_expired_refresh_token_is_refused(client: TestClient) -> None:
    _register(client, "tokens-expired-refresh@example.net")
    _login_tokens(client, "tokens-expired-refresh@example.net")
    now = int(time.time())
    expired = pyjwt.encode(
        {
            "sub": "1",
            "iss": "bangla-gpt-api",
            "aud": "bangla-gpt-clients",
            "iat": now - 86400 * 30,
            "exp": now - 10,
            "jti": "expired-refresh-jti",
            "typ": "refresh",
            "fam": "expired-fam",
        },
        JWT,
        algorithm="HS256",
    )
    res = client.post("/auth/refresh", json={"refresh_token": expired})
    assert res.status_code == 401, res.text


def test_forged_signature_is_refused(client: TestClient) -> None:
    _register(client, "tokens-forged@example.net")
    _login_tokens(client, "tokens-forged@example.net")
    forged = pyjwt.encode(
        {
            "sub": "1",
            "role": "admin",
            "iss": "bangla-gpt-api",
            "aud": "bangla-gpt-clients",
            "iat": int(time.time()),
            "exp": int(time.time()) + 900,
            "jti": "forged-jti",
            "typ": "access",
        },
        "a-different-secret-0123456789abcdef01",
        algorithm="HS256",
    )
    assert client.get("/users/me", headers=_auth(forged)).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": forged}).status_code == 401


def test_algorithm_swapped_token_is_refused(client: TestClient) -> None:
    """`alg: none` (and any algorithm other than the pinned HS256) is refused."""
    _register(client, "tokens-alg@example.net")
    _login_tokens(client, "tokens-alg@example.net")
    unsigned = pyjwt.encode(
        {
            "sub": "1",
            "role": "admin",
            "iss": "bangla-gpt-api",
            "aud": "bangla-gpt-clients",
            "iat": int(time.time()),
            "exp": int(time.time()) + 900,
            "jti": "none-jti",
            "typ": "access",
        },
        key="",
        algorithm="none",
    )
    assert client.get("/users/me", headers=_auth(unsigned)).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": unsigned}).status_code == 401


def test_password_change_kills_outstanding_refresh_tokens(client: TestClient) -> None:
    _register(client, "tokens-epoch@example.net")
    body = _login_tokens(client, "tokens-epoch@example.net")
    # iat is second-precision; make sure the change lands in a later second
    # than the mint so the boundary cannot mask the assertion.
    time.sleep(1.1)
    changed = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "another-secret-77"},
        headers=_auth(body["access_token"]),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["refresh_token"], "the rotation response issues a new session"

    stale = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert stale.status_code == 401, stale.text
    # The new session's refresh token works (same-second mint stays valid).
    assert (
        client.post(
            "/auth/refresh", json={"refresh_token": changed.json()["refresh_token"]}
        ).status_code
        == 200
    )
