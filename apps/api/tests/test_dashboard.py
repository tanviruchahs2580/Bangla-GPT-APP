from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"


def _client(tmp_path):
    s = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/dash.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(s))


def _register_login(client, email="dash@example.com"):
    client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Test",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    tok = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {tok}"}


def test_dashboard_summary_requires_auth(tmp_path):
    c = _client(tmp_path)
    assert c.get("/dashboard/summary").status_code == 401


def test_dashboard_summary_for_new_student(tmp_path):
    c = _client(tmp_path)
    h = _register_login(c, "dash1@example.com")
    r = c.get("/dashboard/summary", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert "user" in j
    assert "today" in j
    assert "quick_actions" in j
    assert len(j["quick_actions"]) == 3
    assert j["progress"] is not None
    # No continue yet (no quiz)
    assert j["continue_learning"] is None


def test_dashboard_summary_with_quiz_gives_continue_and_recommendation(tmp_path):
    c = _client(tmp_path)
    h = _register_login(c, "dash2@example.com")
    # get profile id
    me = c.get("/users/me", headers=h).json()
    pid = me["profile_id"]
    # start and submit quiz to create weak data
    q = c.post(
        "/quizzes",
        json={"student_id": pid, "class_level": 6, "subject": "science", "num_questions": 3},
        headers=h,
    ).json()
    ans = [0] * len(q["questions"])
    c.post(f"/quizzes/{q['attempt_id']}/submit", json={"answers": ans}, headers=h)
    # now dashboard should have continue and maybe recommendation
    r = c.get("/dashboard/summary", headers=h)
    assert r.status_code == 200
    j = r.json()
    # continue should be present (from last quiz)
    assert j["continue_learning"] is not None
    assert j["continue_learning"]["chapter"]
    # progress should have graded
    assert j["progress"]["attempts_graded"] == 1
