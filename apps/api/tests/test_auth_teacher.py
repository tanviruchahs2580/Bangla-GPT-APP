from datetime import UTC, datetime, timedelta

import jwt as pyjwt
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
        database_url=f"sqlite:///{tmp_path}/auth.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str = "student", class_level: int | None = 6):
    payload: dict = {
        "email": email,
        "password": PASSWORD,
        "name": "à¦¶à¦¿à¦•à§à¦·à¦¾à¦°à§à¦¥à§€" if role == "student" else "à¦¶à¦¿à¦•à§à¦·à¦•",
        "role": role,
    }
    if class_level is not None and role == "student":
        payload["class_level"] = class_level
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login_headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_full_register_login_roundtrip(client: TestClient) -> None:
    _register(client, "t1@example.com", role="teacher")
    headers = _login_headers(client, "t1@example.com")
    roster = client.get("/teacher/students", headers=headers)
    assert roster.status_code == 200
    assert roster.json() == []


def test_duplicate_email_rejected(client: TestClient) -> None:
    _register(client, "dup@example.com")
    res = client.post(
        "/auth/register",
        json={
            "email": "dup@example.com",
            "password": PASSWORD,
            "name": "à¦…à¦¨à§à¦¯",
            "role": "student",
            "class_level": 7,
        },
    )
    assert res.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "a@b.com", "password": PASSWORD, "name": "à¦•à§‡à¦‰", "role": "student"},
        {"email": "not-an-email", "password": PASSWORD, "name": "à¦•à§‡à¦‰", "role": "student"},
        {
            "email": "b@c.com",
            "password": "short",
            "name": "à¦•à§‡à¦‰",
            "role": "student",
            "class_level": 6,
        },
    ],
)
def test_registration_validation_failures(client: TestClient, payload: dict) -> None:
    assert client.post("/auth/register", json=payload).status_code == 422


def test_login_failure_cases(client: TestClient) -> None:
    _register(client, "login@example.com")
    wrong_password = client.post(
        "/auth/login", json={"email": "login@example.com", "password": "wrong-password"}
    )
    assert wrong_password.status_code == 401
    unknown = client.post("/auth/login", json={"email": "ghost@example.com", "password": PASSWORD})
    assert unknown.status_code == 401
    normalized = client.post(
        "/auth/login", json={"email": "LOGIN@example.com", "password": PASSWORD}
    )
    assert normalized.status_code == 200


def test_missing_token_is_401(client: TestClient) -> None:
    assert client.get("/teacher/students").status_code == 401
    assert client.get("/students/1/progress").status_code == 401


def test_student_role_forbidden_on_teacher_endpoints(client: TestClient) -> None:
    _register(client, "s@example.com", role="student")
    headers = _login_headers(client, "s@example.com")
    assert client.get("/teacher/students", headers=headers).status_code == 403
    assert client.get("/teacher/classes/6/analytics", headers=headers).status_code == 403


def test_expired_token_rejected(client: TestClient) -> None:
    _register(client, "exp@example.com", role="teacher")
    expired = pyjwt.encode(
        {"sub": "1", "role": "teacher", "exp": datetime.now(UTC) - timedelta(minutes=5)},
        SECRET,
        algorithm="HS256",
    )
    res = client.get("/teacher/students", headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401


def test_forged_token_rejected(client: TestClient) -> None:
    forged = pyjwt.encode(
        {"sub": "1", "role": "teacher", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "wrong-secret",
        algorithm="HS256",
    )
    res = client.get("/teacher/students", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401
    garbage = client.get("/teacher/students", headers={"Authorization": "Bearer not.a.jwt"})
    assert garbage.status_code == 401


def test_cross_student_data_isolation_and_teacher_access(client: TestClient) -> None:
    a_id, a_headers = None, None
    profile_a = _register(client, "alice@example.com")
    a_id, a_headers = profile_a["profile_id"], _login_headers(client, "alice@example.com")

    _register(client, "bob@example.com")
    b_headers = _login_headers(client, "bob@example.com")

    started = client.post(
        "/quizzes",
        json={"student_id": a_id, "num_questions": 3},
        headers=a_headers,
    ).json()
    submitted = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
        headers=a_headers,
    )
    assert submitted.status_code == 200

    bob_view_progress = client.get(f"/students/{a_id}/progress", headers=b_headers)
    assert bob_view_progress.status_code == 403
    bob_submit = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
        headers=b_headers,
    )
    assert bob_submit.status_code in (400, 403)

    _register(client, "teach@example.com", role="teacher")
    teacher_headers = _login_headers(client, "teach@example.com")
    teacher_view = client.get(f"/students/{a_id}/progress", headers=teacher_headers)
    assert teacher_view.status_code == 200
    teacher_generate = client.post(
        "/quizzes", json={"student_id": a_id, "num_questions": 2}, headers=teacher_headers
    )
    assert teacher_generate.status_code == 200


def test_teacher_roster_and_class_analytics(client: TestClient) -> None:
    for i, email in enumerate(["c1@example.com", "c2@example.com"], start=1):
        _register(client, email, class_level=6)
        headers = _login_headers(client, email)
        started = client.post(
            "/quizzes", json={"student_id": i, "num_questions": 3}, headers=headers
        ).json()
        client.post(
            f"/quizzes/{started['attempt_id']}/submit",
            json={"answers": [3] * len(started["questions"])},
            headers=headers,
        )

    _register(client, "classteach@example.com", role="teacher")
    teacher = _login_headers(client, "classteach@example.com")

    roster = client.get("/teacher/students", params={"class_level": 6}, headers=teacher).json()
    assert len(roster) == 2
    assert all(entry["attempts_graded"] == 1 for entry in roster)

    analytics = client.get("/teacher/classes/6/analytics", headers=teacher).json()
    assert analytics["class_level"] == 6
    assert analytics["students"] == 2
    assert analytics["chapters"], "expected chapter stats from graded attempts"
    assert all(c["accuracy"] < 60.0 for c in analytics["chapters"])
    assert set(analytics["weak_chapters"]) == {c["chapter"] for c in analytics["chapters"]}
    assert len(analytics["students_detail"]) == 2

    empty = client.get("/teacher/classes/9/analytics", headers=teacher).json()
    assert empty["students"] == 0 and empty["chapters"] == []
