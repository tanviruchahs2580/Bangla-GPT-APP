import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/admin.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
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


def test_bootstrap_admin_exists_and_can_list_users(client: TestClient) -> None:
    headers = _login_headers(client, "root@example.com")
    users = client.get("/admin/users", headers=headers)
    assert users.status_code == 200
    roles = [u["role"] for u in users.json()["items"]]
    assert roles.count("admin") >= 1


def test_admin_endpoints_reject_non_admins_and_anonymous(client: TestClient) -> None:
    _register(client, "t@example.com", role="teacher")
    teacher = _login_headers(client, "t@example.com")
    assert client.get("/admin/users").status_code == 401
    assert client.get("/admin/users", headers=teacher).status_code == 403
    assert client.get("/admin/analytics/overview", headers=teacher).status_code == 403


def test_admin_can_promote_and_role_takes_effect(client: TestClient) -> None:
    profile = _register(client, "up@example.com", role="teacher")
    root = _login_headers(client, "root@example.com")
    res = client.patch(
        f"/admin/users/{profile['user_id']}/role",
        json={"role": "admin"},
        headers=root,
    )
    assert res.status_code == 200
    assert res.json()["role"] == "admin"
    promoted_headers = _login_headers(client, "up@example.com")
    assert client.get("/admin/users", headers=promoted_headers).status_code == 200


def test_cannot_demote_last_admin(client: TestClient) -> None:
    root = _login_headers(client, "root@example.com")
    users = client.get("/admin/users", headers=root).json()["items"]
    admin_user = next(u for u in users if u["role"] == "admin")
    res = client.patch(
        f"/admin/users/{admin_user['id']}/role", json={"role": "student"}, headers=root
    )
    assert res.status_code == 409


def test_register_cannot_create_admin_role(client: TestClient) -> None:
    res = client.post(
        "/auth/register",
        json={"email": "evil@example.com", "password": PASSWORD, "name": "x", "role": "admin"},
    )
    assert res.status_code == 422


def test_admin_overview_counts(client: TestClient) -> None:
    for i in range(2):
        _register(client, f"s{i}@example.com")
        headers = _login_headers(client, f"s{i}@example.com")
        started = client.post(
            "/quizzes", json={"student_id": i + 1, "num_questions": 2}, headers=headers
        ).json()
        client.post(
            f"/quizzes/{started['attempt_id']}/submit",
            json={"answers": [0] * len(started["questions"])},
            headers=headers,
        )
    _register(client, "teach@example.com", role="teacher")

    overview = client.get(
        "/admin/analytics/overview", headers=_login_headers(client, "root@example.com")
    ).json()
    assert overview["students"] == 2
    assert overview["teachers"] == 1
    assert overview["admins"] >= 1
    assert overview["quiz_attempts_graded"] == 2
    assert overview["avg_score_pct"] is not None


def test_rate_limit_login_429(tmp_path) -> None:
    client = make_client(tmp_path, rate_limit_login_per_minute=2)
    for _ in range(2):
        res = client.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
        assert res.status_code == 401
    third = client.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert third.status_code == 429
    assert third.json()["detail"]["code"] == "rate_limited"


def test_rate_limit_scoped_to_configured_paths(tmp_path) -> None:
    client = make_client(tmp_path, rate_limit_login_per_minute=2)
    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_body_size_limit_413(tmp_path) -> None:
    client = make_client(tmp_path, max_body_bytes=64)
    big_question = "ক" * 500
    res = client.post(
        "/tutor/ask",
        json={"question": big_question, "class_level": 6},
    )
    assert res.status_code == 413


def test_normal_payload_passes_size_guard(client: TestClient) -> None:
    _register(client, "size@example.com")
    headers = _login_headers(client, "size@example.com")
    res = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6},
        headers=headers,
    )
    assert res.status_code == 200
