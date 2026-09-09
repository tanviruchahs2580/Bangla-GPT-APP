"""Wave 1: saved notes -- private, per-user scratch pad."""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/notes.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str = "student") -> None:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Person", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    assert client.post("/auth/register", json=payload).status_code == 201


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_create_default_title_round_trip_and_delete(client: TestClient) -> None:
    _register(client, "kid@example.com")
    headers = _headers(client, "kid@example.com")

    res = client.post("/notes", json={"body": "  " + "note body " * 3}, headers=headers)
    assert res.status_code == 201, res.text
    note = res.json()
    assert note["id"] > 0
    assert note["title"].startswith("note body")
    assert note["source"] == "other"
    assert note["source_ref"] is None
    assert note["created_at"]

    res = client.post(
        "/notes",
        json={
            "title": "Cell recap",
            "body": "mitochondria is the powerhouse",
            "source": "chapter",
            "source_ref": {"chapter": "kosh", "class_level": 6},
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    second = res.json()
    assert second["title"] == "Cell recap"
    assert second["source"] == "chapter"
    assert second["source_ref"] == {"chapter": "kosh", "class_level": 6}

    listing = client.get("/notes", headers=headers).json()
    assert [n["id"] for n in listing] == [second["id"], note["id"]]  # newest first

    assert client.delete(f"/notes/{note['id']}", headers=headers).status_code == 204
    assert client.get("/notes", headers=headers).json() == [second]
    assert client.delete(f"/notes/{note['id']}", headers=headers).status_code == 404


def test_notes_are_private_between_users(client: TestClient) -> None:
    _register(client, "a@example.com")
    _register(client, "b@example.com")
    a = _headers(client, "a@example.com")
    b = _headers(client, "b@example.com")
    res = client.post("/notes", json={"body": "private thought"}, headers=a)
    assert res.status_code == 201
    note_id = res.json()["id"]

    assert client.get("/notes", headers=b).json() == []
    assert client.delete(f"/notes/{note_id}", headers=b).status_code == 404
    assert len(client.get("/notes", headers=a).json()) == 1


def test_note_validation(client: TestClient) -> None:
    _register(client, "kid@example.com")
    headers = _headers(client, "kid@example.com")
    assert client.post("/notes", json={"body": ""}, headers=headers).status_code == 422
    assert (
        client.post("/notes", json={"body": "ok", "source": "bogus"}, headers=headers).status_code
        == 422
    )
    assert client.post("/notes", json={"body": "x" * 20001}, headers=headers).status_code == 422


def test_notes_require_authentication(client: TestClient) -> None:
    assert client.get("/notes").status_code == 401
    assert client.post("/notes", json={"body": "x"}).status_code == 401
    assert client.delete("/notes/1").status_code == 401
