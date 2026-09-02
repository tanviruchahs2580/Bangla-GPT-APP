"""B4 — self-service data export (GDPR-style portability)."""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/export.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        allow_direct_parent_link=True,  # legacy mode under test
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str, **extra) -> dict:
    payload = {"email": email, "password": PASSWORD, "name": "নাম", "role": role, **extra}
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_export_requires_auth(client: TestClient) -> None:
    assert client.get("/users/me/export").status_code == 401


def test_student_export_contains_attempts_and_links(client: TestClient) -> None:
    student = _register(client, "s@example.com", "student", guardian_consent=True, class_level=6)
    parent_profile = _register(client, "p@example.com", "parent")
    parent_headers = _headers(client, "p@example.com")
    linked = client.post(
        "/parents/link", json={"student_id": student["profile_id"]}, headers=parent_headers
    )
    assert linked.status_code == 201

    student_headers = _headers(client, "s@example.com")
    started = client.post(
        "/quizzes",
        json={"student_id": student["profile_id"], "num_questions": 2},
        headers=student_headers,
    ).json()
    submitted = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
        headers=student_headers,
    )
    assert submitted.status_code == 200

    export = client.get("/users/me/export", headers=student_headers)
    assert export.status_code == 200
    assert "attachment" in export.headers.get("content-disposition", "")

    body = export.json()
    assert body["user"]["email"] == "s@example.com"
    assert body["user"]["role"] == "student"
    assert body["profile"]["type"] == "student"
    assert body["profile"]["class_level"] == 6
    assert len(body["quiz_attempts"]) == 1
    attempt = body["quiz_attempts"][0]
    assert attempt["status"] == "graded"
    assert attempt["total"] == len(started["questions"])
    assert body["parent_links"] == [
        {"direction": "linked_by", "parent_id": parent_profile["profile_id"]}
    ]


def test_teacher_and_parent_exports(client: TestClient) -> None:
    _register(client, "t@example.com", "teacher")
    teacher_body = client.get("/users/me/export", headers=_headers(client, "t@example.com")).json()
    assert teacher_body["profile"]["type"] == "teacher"
    assert teacher_body["quiz_attempts"] == []

    _register(client, "pp@example.com", "parent")
    parent_body = client.get("/users/me/export", headers=_headers(client, "pp@example.com")).json()
    assert parent_body["profile"]["type"] == "parent"
