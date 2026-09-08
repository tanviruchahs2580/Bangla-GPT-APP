"""S1.8 — chat history: rename, delete, and message search."""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/history.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


def _register_login(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "supersecret1",
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    login = client.post("/auth/login", json={"email": email, "password": "supersecret1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def student(client: TestClient) -> dict[str, str]:
    return _register_login(client, "h1@example.com")


@pytest.fixture
def other_student(client: TestClient) -> dict[str, str]:
    return _register_login(client, "h2@example.com")


def _conv_with_message(client: TestClient, auth: dict) -> int:
    conv = client.post("/tutor/conversations", headers=auth, json={}).json()
    cid = conv["id"]
    r = client.post(
        f"/tutor/conversations/{cid}/messages",
        headers=auth,
        json={"message": "কোষ কী? বলো তো"},
    )
    assert r.status_code == 200, r.text
    return cid


def test_rename_conversation_persists(client: TestClient, student: dict) -> None:
    cid = _conv_with_message(client, student)
    r = client.patch(f"/tutor/conversations/{cid}", headers=student, json={"title": "কোষ অধ্যায়"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "কোষ অধ্যায়"
    listed = client.get("/tutor/conversations", headers=student).json()
    assert [c["title"] for c in listed if c["id"] == cid] == ["কোষ অধ্যায়"]


def test_rename_rejects_blank_and_too_long(client: TestClient, student: dict) -> None:
    cid = _conv_with_message(client, student)
    assert (
        client.patch(f"/tutor/conversations/{cid}", headers=student, json={"title": ""}).status_code
        == 422
    )
    assert (
        client.patch(
            f"/tutor/conversations/{cid}", headers=student, json={"title": "ক" * 121}
        ).status_code
        == 422
    )


def test_delete_conversation_removes_messages(client: TestClient, student: dict) -> None:
    cid = _conv_with_message(client, student)
    r = client.delete(f"/tutor/conversations/{cid}", headers=student)
    assert r.status_code == 204
    listed = client.get("/tutor/conversations", headers=student).json()
    assert cid not in [c["id"] for c in listed]
    assert client.get(f"/tutor/conversations/{cid}/messages", headers=student).status_code == 404


def test_cannot_touch_others_conversation(
    client: TestClient, student: dict, other_student: dict
) -> None:
    cid = _conv_with_message(client, student)
    assert (
        client.patch(
            f"/tutor/conversations/{cid}", headers=other_student, json={"title": "x"}
        ).status_code
        == 403
    )
    assert client.delete(f"/tutor/conversations/{cid}", headers=other_student).status_code == 403
    # Search must not leak other students' messages either.
    hits = client.get("/tutor/messages/search", headers=other_student, params={"q": "কোষ"}).json()
    assert hits == []


def test_message_search_finds_own_history(client: TestClient, student: dict) -> None:
    cid = _conv_with_message(client, student)
    r = client.get("/tutor/messages/search", headers=student, params={"q": "কোষ"})
    assert r.status_code == 200
    hits = r.json()
    assert hits, "expected the sent message to match"
    hit = hits[0]
    assert hit["conversation_id"] == cid
    assert "কোষ" in hit["snippet"]
    # Wildcards in the query are literal, not LIKE operators.
    r2 = client.get("/tutor/messages/search", headers=student, params={"q": "%%"})
    assert r2.json() == []
    # Too-short queries are rejected.
    short = client.get("/tutor/messages/search", headers=student, params={"q": "ক"})
    assert short.status_code == 422
