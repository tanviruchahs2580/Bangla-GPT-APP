"""SEC-11/19 wave-2 guards: the abuse paths the audit named are rated, and
the business-logic surfaces are honest.

F-147: `/auth/join-school` is unauthenticated, redeems a staff invite code
and creates a staff account on success -- 14 rapid guesses all answered 404
with no 429. F-148: the personal-data export and the platform aggregate
report carried no rate-limit rule, so one account could repeatedly
materialise its whole data set. F-127: `/users` was never covered at all,
including DELETE /users/me, which re-verifies the current password with
Argon2id on every call.

The SEC-19 half asserts the surfaces the audit found HONEST, so a future
change cannot quietly turn them into a defect: answers are not in the quiz
payload before submission, the streak cannot be written by a client and
follows real graded work, rotating conversation ids cannot multiply a
per-user tutor budget, and registration stays bounded.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.initialize.middleware_stack import _effective_rules
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _settings(tmp_path, **over) -> Settings:
    base = dict(
        env="test",
        database_url=engine_url(tmp_path, "w2limits"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    base.update(over)
    return Settings(**base)


def _client(tmp_path, **over) -> TestClient:
    return TestClient(create_app(_settings(tmp_path, **over)))


def _register(client: TestClient, email: str, role: str = "student", **extra) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Tester", "role": role, **extra}
    if role == "student":
        payload.setdefault("guardian_consent", True)
        payload.setdefault("class_level", 6)
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _rule_for(rules: dict[str, tuple[int, str]], path: str) -> tuple[int, str] | None:
    for prefix, rule in rules.items():
        if path == prefix or path.startswith(prefix + "/"):
            return rule
    return None


def _registered_paths(app) -> set[str]:
    """Every path the app serves, taken from its own OpenAPI document.

    FastAPI 0.143 wraps ``include_router`` in an opaque handle whose routes
    are NOT in ``app.routes``, so a flat scan sees only /docs and the health
    probes -- exactly the trap that made the pre-existing "no costly route is
    left unrated" test vacuous. The served document is the honest source
    (120 paths here, 4 through ``app.routes``).
    """
    return set(app.openapi()["paths"])


# --- F-147/F-148/F-127: the unrated abuse paths ----------------------------


def _registered_paths(app) -> set[str]:
    """Every path the app serves, taken from its own OpenAPI document.

    FastAPI 0.143 wraps ``include_router`` in an opaque handle whose routes
    are NOT in ``app.routes``, so a flat scan sees only /docs and the health
    probes -- exactly the trap that made the pre-existing
    "no costly route is left unrated" test vacuous. The served document is
    the honest source (120 paths here, 4 through ``app.routes``).
    """
    return set(app.openapi()["paths"])


@pytest.mark.parametrize(
    "path,scope",
    [
        ("/auth/join-school", "ip"),
        ("/users/me/export", "user"),
        ("/users/me", "user"),
        ("/admin/reports/aggregate", "user"),
    ],
)
def test_previously_unrated_paths_ship_with_a_rule(path: str, scope: str) -> None:
    """Derived from the app's own route table, so the rule cannot rot."""
    app = create_app(_settings(None, database_url="sqlite:///:memory:"))
    rules = _effective_rules(app.state.settings)
    # the prefix must match at least one real route, so a typo in the rule
    # table (or a renamed route) fails here instead of silently unrating it
    paths = _registered_paths(app)
    assert any(p == path or p.startswith(path) for p in paths), (
        f"no route {path} in {len(paths)} paths"
    )
    rule = _rule_for(rules, path)
    assert rule is not None, f"{path} has no rate-limit rule (F-147/F-148/F-127)"
    assert rule[0] > 0 and rule[1] == scope


def test_join_school_enumeration_is_rate_limited(tmp_path) -> None:
    """14 rapid guessing attempts must hit 429 instead of a free oracle."""
    client = _client(tmp_path)
    statuses = [
        client.post(
            "/auth/join-school",
            json={
                "invite_code": f"BGPT-{i:08X}",
                "email": f"probe{i}@example.com",
                "password": PASSWORD,
                "name": "Probe",
            },
        )
        for i in range(11)
    ]
    # the first ten reach the handler and are refused for the wrong code,
    # the eleventh is refused by the limiter before any lookup
    assert all(s.status_code in (400, 404) for s in statuses[:10]), [s.text for s in statuses[:10]]
    assert statuses[10].status_code == 429
    assert statuses[10].json()["detail"]["code"] == "rate_limited"


def test_export_is_rate_limited_per_user(tmp_path) -> None:
    client = _client(tmp_path, rate_limit_rules={"/users/me/export": (5, "user")})
    _register(client, "export@example.com")
    headers = _headers(client, "export@example.com")
    statuses = [client.get("/users/me/export", headers=headers) for _ in range(6)]
    assert [s.status_code for s in statuses[:5]] == [200] * 5
    assert statuses[5].status_code == 429
    assert statuses[5].json()["detail"]["code"] == "rate_limited"


def test_delete_me_password_check_is_rate_limited(tmp_path) -> None:
    """F-127: re-auth on DELETE /users/me must not be an unthrottled oracle."""
    client = _client(tmp_path, rate_limit_rules={"/users/me": (3, "user")})
    _register(client, "del@example.com")
    headers = _headers(client, "del@example.com")
    statuses = [
        client.request("DELETE", "/users/me", json={"password": f"wrong{i}"}, headers=headers)
        for i in range(4)
    ]
    assert [s.status_code for s in statuses[:3]] == [401] * 3
    assert statuses[3].status_code == 429


# --- SEC-19: business-logic abuse paths ------------------------------------


def test_answers_are_not_exposed_before_submission(tmp_path) -> None:
    """The quiz payload must not carry the answer key."""
    client = _client(tmp_path)
    student = _register(client, "quiz@example.com")
    headers = _headers(client, "quiz@example.com")
    started = client.post(
        "/quizzes",
        json={"student_id": student["profile_id"], "num_questions": 3},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["questions"], "the quiz must serve questions"
    for question in body["questions"]:
        leaked = {
            key
            for key in question
            if key in {"answer_index", "correct_index", "answer", "answers", "correct"}
        }
        assert not leaked, f"question leaks {leaked} before submission"
        assert not any(isinstance(v, int) and k == "answer" for k, v in question.items())


def test_streak_is_server_derived_and_not_writable(tmp_path) -> None:
    """A client must not be able to set its own activity counters."""
    client = _client(tmp_path)
    student = _register(client, "streak@example.com")
    headers = _headers(client, "streak@example.com")
    sid = student["profile_id"]

    before = client.get(f"/students/{sid}/activity", headers=headers)
    assert before.status_code == 200
    assert before.json()["streak"] == 0

    # every write-shaped verb against the activity surface is refused
    assert client.post(
        f"/students/{sid}/activity", json={"streak": 99}, headers=headers
    ).status_code in (404, 405)
    assert client.patch(
        f"/students/{sid}/activity", json={"streak": 99}, headers=headers
    ).status_code in (404, 405)

    # and the streak follows REAL graded work only
    started = client.post(
        "/quizzes", json={"student_id": sid, "num_questions": 2}, headers=headers
    ).json()
    submitted = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
        headers=headers,
    )
    assert submitted.status_code == 200, submitted.text
    after = client.get(f"/students/{sid}/activity", headers=headers).json()
    assert after["streak"] == 1, "one graded quiz is one active day"
    assert after["days"], "the heatmap must show the graded day"


def test_conversation_rotation_cannot_multiply_the_tutor_budget(tmp_path) -> None:
    """The limiter is keyed per user, not per conversation (SEC-19)."""
    # the chat routes are per-field knobs (RATE_LIMIT_TUTOR_PER_MINUTE),
    # so the budget is set there; the IP ceiling is raised so the user
    # budget is what this test measures
    client = _client(
        tmp_path,
        rate_limit_tutor_per_minute=3,
        rate_limit_tutor_ip_per_minute=1000,
        llm_provider="mock",
    )
    _register(client, "chat@example.com")
    headers = _headers(client, "chat@example.com")

    conversations = [
        client.post("/tutor/conversations", json={"title": f"chat {i}"}, headers=headers)
        for i in range(3)
    ]
    assert all(c.status_code == 201 for c in conversations), [c.text for c in conversations]
    ids = [c.json()["id"] for c in conversations]
    assert len(set(ids)) == 3

    # a fourth request -- on a BRAND NEW conversation id -- is still refused:
    # rotating ids must not reset the per-user window
    fourth = client.post("/tutor/conversations", json={"title": "chat 4"}, headers=headers)
    assert fourth.status_code == 429
    message = client.post(
        f"/tutor/conversations/{ids[0]}/messages",
        json={"message": "hi"},
        headers=headers,
    )
    assert message.status_code == 429
    assert message.json()["detail"]["code"] == "rate_limited"


def test_mass_registration_is_bounded(tmp_path) -> None:
    """Registration runs Argon2id per call; the 11th from one IP is refused."""
    client = _client(tmp_path)
    for i in range(10):
        assert _register(client, f"mass{i}@example.com")["user_id"]
    refused = client.post(
        "/auth/register",
        json={
            "email": "mass10@example.com",
            "password": PASSWORD,
            "name": "Tester",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "rate_limited"
