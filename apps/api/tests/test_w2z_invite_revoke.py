"""F-IV2-3: guardian-invite revocation must be reachable from the API.

The wave-2 F-145 fix added ``DELETE /students/me/invite-code/{invite_id}``
but the create response carried only the code, no route listed the caller's
invites, and no client could obtain the id without reading the database --
so a student who leaked a code could not actually revoke it. These guards
pin the id to the create response and to a list route that never returns
the code itself.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2zinvite"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str = "student") -> None:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Tester", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_revoke_by_the_id_from_the_create_response(client) -> None:
    _register(client, "kid@example.com")
    _register(client, "mom@example.com", role="parent")
    kid = _headers(client, "kid@example.com")
    parent = _headers(client, "mom@example.com")

    created = client.post("/students/me/invite-code", headers=kid)
    assert created.status_code == 201, created.text
    body = created.json()
    assert isinstance(body["id"], int) and body["id"] > 0
    code = body["code"]

    revoked = client.delete(f"/students/me/invite-code/{body['id']}", headers=kid)
    assert revoked.status_code == 204, revoked.text

    # The revoked code can no longer attach a guardian to the child.
    refused = client.post("/parents/link/invite", json={"code": code}, headers=parent)
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"]["code"] == "invalid_invite"


def test_list_returns_live_ids_and_never_the_code(client) -> None:
    _register(client, "kid@example.com")
    kid = _headers(client, "kid@example.com")

    created = client.post("/students/me/invite-code", headers=kid).json()
    listed = client.get("/students/me/invite-code", headers=kid)
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert [row["id"] for row in rows] == [created["id"]]
    assert "code" not in rows[0]
    assert created["code"] not in listed.text

    # The listed id is revocable, and a revoked code leaves the live list.
    revoked = client.delete(f"/students/me/invite-code/{rows[0]['id']}", headers=kid)
    assert revoked.status_code == 204, revoked.text
    assert client.get("/students/me/invite-code", headers=kid).json() == []
