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
        database_url=f"sqlite:///{tmp_path}/parent.db",
        allow_direct_parent_link=True,  # legacy mode under test
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str, class_level: int | None = None):
    payload: dict = {"email": email, "password": PASSWORD, "name": "নাম", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        if class_level is not None:
            payload["class_level"] = class_level
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login(client: TestClient, email: str):
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_parent_link_and_view_progress(client: TestClient) -> None:
    student = _register(client, "child@example.com", role="student", class_level=6)
    _register(client, "mom@example.com", role="parent")
    student_headers = _login(client, "child@example.com")
    parent_headers = _login(client, "mom@example.com")

    started = client.post(
        "/quizzes",
        json={"student_id": student["profile_id"], "num_questions": 2},
        headers=student_headers,
    ).json()
    client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
        headers=student_headers,
    )

    link = client.post(
        "/parents/link", json={"student_id": student["profile_id"]}, headers=parent_headers
    )
    assert link.status_code == 201

    children = client.get("/parents/me/children", headers=parent_headers).json()
    assert len(children) == 1
    assert children[0]["student_id"] == student["profile_id"]

    progress = client.get(
        f"/parents/me/children/{student['profile_id']}/progress", headers=parent_headers
    )
    assert progress.status_code == 200
    assert progress.json()["attempts_graded"] == 1


def test_parent_isolation_and_validation(client: TestClient) -> None:
    s1 = _register(client, "c1@example.com", role="student", class_level=6)
    s2 = _register(client, "c2@example.com", role="student", class_level=6)
    _register(client, "p1@example.com", role="parent")
    _register(client, "p2@example.com", role="parent")
    p1_headers = _login(client, "p1@example.com")
    p2_headers = _login(client, "p2@example.com")
    s_headers = _login(client, "c1@example.com")

    client.post("/parents/link", json={"student_id": s1["profile_id"]}, headers=p1_headers)
    client.post("/parents/link", json={"student_id": s2["profile_id"]}, headers=p2_headers)

    assert (
        client.get(
            f"/parents/me/children/{s2['profile_id']}/progress", headers=p1_headers
        ).status_code
        == 404
    )
    assert client.get("/parents/me/children", headers=s_headers).status_code == 403
    duplicate = client.post(
        "/parents/link", json={"student_id": s1["profile_id"]}, headers=p1_headers
    )
    assert duplicate.status_code == 409
    unknown = client.post("/parents/link", json={"student_id": 999}, headers=p1_headers)
    assert unknown.status_code == 404


def test_anonymous_and_wrong_role_rejected(client: TestClient) -> None:
    assert client.get("/parents/me/children").status_code == 401
    s = _register(client, "x@example.com", role="student", class_level=6)
    s_headers = _login(client, "x@example.com")
    assert (
        client.post(
            "/parents/link", json={"student_id": s["profile_id"]}, headers=s_headers
        ).status_code
        == 403
    )
