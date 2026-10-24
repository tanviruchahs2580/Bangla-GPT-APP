"""S-012/S-003: /quizzes, /teacher/shorttests and /teacher/assignments are rated.

Each of these calls walks the corpus and writes rows per audience member
(one QuizAttempt for /quizzes; one QuizAttempt plus a notification per roster
student for the two fan-out teacher routes), yet none had a rate-limit rule:
the probe recorded 40 consecutive 200/422 and never a 429. These tests assert
the shipped defaults and that the middleware really answers 429.
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.initialize.middleware_stack import _effective_rules
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"

NEW_RULES = {
    "/quizzes": (20, "user"),
    "/teacher/shorttests": (20, "user"),
    "/teacher/assignments": (20, "user"),
}


def _rule_for(rules: dict[str, tuple[int, str]], path: str) -> tuple[int, str] | None:
    for prefix, rule in rules.items():
        if path == prefix or path.startswith(prefix + "/"):
            return rule
    return None


def _make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "quiz-rl"),
        jwt_secret=JWT,
        **overrides,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Person", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.parametrize("path", sorted(NEW_RULES))
def test_rules_ship_by_default(path: str) -> None:
    rules = _effective_rules(Settings(env="test"))
    assert _rule_for(rules, path) == NEW_RULES[path]


def test_rule_format_and_env_override_still_work(tmp_path) -> None:
    """RATE_LIMIT_RULES keeps its (limit, scope) tuple format and precedence."""
    client = _make_client(tmp_path, rate_limit_rules={"/quizzes": (3, "user")})
    assert _rule_for(_effective_rules(client.app.state.settings), "/quizzes") == (3, "user")


def test_quiz_creation_burst_returns_429(tmp_path) -> None:
    client = _make_client(tmp_path, rate_limit_rules={"/quizzes": (2, "user")})
    student_profile = _register(client, "kid@example.test", "student")
    headers = _login(client, "kid@example.test")
    body = {
        "student_id": student_profile["profile_id"],
        "subject": "science",
        "num_questions": 2,
    }

    first = client.post("/quizzes", json=body, headers=headers)
    second = client.post("/quizzes", json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    blocked = client.post("/quizzes", json=body, headers=headers)
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["detail"]["code"] == "rate_limited"


def test_shorttest_and_assignment_bursts_return_429(tmp_path) -> None:
    """The per-student fan-out routes are refused before the handler runs.

    The bodies are deliberately invalid (unknown classroom/student): what is
    under test is that the middleware counts the request and answers 429 on
    the burst, instead of letting the handler's 4xx through forever.
    """
    client = _make_client(
        tmp_path,
        rate_limit_rules={
            "/teacher/shorttests": (2, "user"),
            "/teacher/assignments": (2, "user"),
        },
    )
    _register(client, "teach@example.test", "teacher")
    headers = _login(client, "teach@example.test")

    shorttest = {
        "classroom_id": 999_999,
        "subject": "science",
        "chapter": "কোষ",
        "num_questions": 3,
        "duration_min": 5,
    }
    codes = [
        client.post("/teacher/shorttests", json=shorttest, headers=headers).status_code
        for _ in range(2)
    ]
    assert codes == [404, 404], codes
    blocked = client.post("/teacher/shorttests", json=shorttest, headers=headers)
    assert blocked.status_code == 429, blocked.text

    assignment = {
        "student_ids": [999_999],
        "subject": "science",
        "chapter": "কোষ",
        "num_questions": 3,
        "due_at": "2026-12-01T00:00:00",
    }
    codes = [
        client.post("/teacher/assignments", json=assignment, headers=headers).status_code
        for _ in range(2)
    ]
    assert codes == [404, 404], codes
    blocked = client.post("/teacher/assignments", json=assignment, headers=headers)
    assert blocked.status_code == 429, blocked.text
