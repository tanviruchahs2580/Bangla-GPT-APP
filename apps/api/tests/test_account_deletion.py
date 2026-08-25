import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/deletion.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
        **overrides,
    )
    return TestClient(create_app(settings))


@pytest.fixture
def client(tmp_path) -> TestClient:
    return make_client(tmp_path)


def _register(client: TestClient, email: str, role: str = "student", class_level: int | None = 6):
    payload: dict = {"email": email, "password": PASSWORD, "name": "নাম", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        if class_level is not None:
            payload["class_level"] = class_level
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login_headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_delete_me_requires_authentication(client: TestClient) -> None:
    assert client.delete("/users/me").status_code == 401


def test_users_me_returns_profile(client: TestClient) -> None:
    profile = _register(client, "me@example.com", role="student", class_level=7)
    headers = _login_headers(client, "me@example.com")
    res = client.get("/users/me", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "user_id": profile["user_id"],
        "email": "me@example.com",
        "role": "student",
        "profile_id": profile["profile_id"],
        "name": "নাম",
        "class_level": 7,
    }


def test_student_deletion_removes_account_and_data(client: TestClient) -> None:
    student = _register(client, "del@example.com")
    headers = _login_headers(client, "del@example.com")

    started = client.post(
        "/quizzes",
        json={"student_id": student["profile_id"], "num_questions": 2},
        headers=headers,
    ).json()
    client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
        headers=headers,
    )

    _register(client, "parent@example.com", role="parent")
    parent_headers = _login_headers(client, "parent@example.com")
    link = client.post(
        "/parents/link", json={"student_id": student["profile_id"]}, headers=parent_headers
    )
    assert link.status_code == 201

    old_token_headers = dict(headers)
    res = client.delete("/users/me", headers=headers)
    assert res.status_code == 204
    assert res.content == b""

    assert (
        client.post(
            "/auth/login", json={"email": "del@example.com", "password": PASSWORD}
        ).status_code
        == 401
    )

    res = client.get("/users/me", headers=old_token_headers)
    assert res.status_code in (401, 404)

    children = client.get("/parents/me/children", headers=parent_headers).json()
    assert children == []

    root = _login_headers(client, "root@example.com")
    overview = client.get("/admin/analytics/overview", headers=root).json()
    assert overview["students"] == 0
    assert overview["quiz_attempts_graded"] == 0


def test_parent_deletion_removes_links_but_keeps_student(client: TestClient) -> None:
    _register(client, "kid@example.com")
    parent = _register(client, "p2@example.com", role="parent")
    parent_headers = _login_headers(client, "p2@example.com")
    client.post("/parents/link", json={"student_id": 1}, headers=parent_headers)

    res = client.delete("/users/me", headers=parent_headers)
    assert res.status_code == 204
    assert parent is not None

    root = _login_headers(client, "root@example.com")
    overview = client.get("/admin/analytics/overview", headers=root).json()
    assert overview["parents"] == 0
    assert overview["students"] == 1


def test_teacher_deletion(client: TestClient) -> None:
    _register(client, "t@example.com", role="teacher")
    headers = _login_headers(client, "t@example.com")
    assert client.delete("/users/me", headers=headers).status_code == 204
    assert client.get("/teacher/students", headers=headers).status_code == 401


def test_last_admin_cannot_self_delete(client: TestClient) -> None:
    root = _login_headers(client, "root@example.com")
    res = client.delete("/users/me", headers=root)
    assert res.status_code == 409
    assert res.json()["detail"] == "Cannot delete the last admin"


def test_second_admin_can_self_delete(client: TestClient) -> None:
    root = _login_headers(client, "root@example.com")
    other = _register(client, "second@example.com", role="teacher")
    promote = client.patch(
        f"/admin/users/{other['user_id']}/role", json={"role": "admin"}, headers=root
    )
    assert promote.status_code == 200
    second_headers = _login_headers(client, "second@example.com")
    assert client.delete("/users/me", headers=second_headers).status_code == 204
    remaining = [u for u in client.get("/admin/users", headers=root).json() if u["role"] == "admin"]
    assert len(remaining) >= 1
    assert all(u["id"] != other["user_id"] for u in remaining)
