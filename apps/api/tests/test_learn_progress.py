"""S1.2 — chapter progress: upsert/get endpoints, badge inputs, authz."""

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"


def _client(tmp_path):
    s = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/lp.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(s))


def _register_login(client, email, role="student"):
    body = {
        "email": email,
        "password": PASSWORD,
        "name": "Progress Tester",
        "role": role,
        "guardian_consent": True,
    }
    if role == "student":
        body["class_level"] = 6
    client.post("/auth/register", json=body)
    tok = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {tok}"}


def test_progress_requires_auth(tmp_path):
    c = _client(tmp_path)
    assert c.get("/learn/progress").status_code == 401


def test_upsert_creates_and_get_returns(tmp_path):
    c = _client(tmp_path)
    h = _register_login(c, "lp1@example.com")
    r = c.post(
        "/learn/progress",
        headers=h,
        json={
            "subject": "science",
            "chapter": "আলোক",
            "class_level": 6,
            "read_pct": 40,
        },
    )
    assert r.status_code == 200
    assert r.json()["read_pct"] == 40
    assert r.json()["completed"] is False
    rows = c.get("/learn/progress", headers=h).json()
    assert len(rows) == 1
    assert rows[0]["chapter"] == "আলোক"
    assert rows[0]["read_pct"] == 40


def test_upsert_partial_update_preserves_fields(tmp_path):
    c = _client(tmp_path)
    h = _register_login(c, "lp2@example.com")
    base = {"subject": "science", "chapter": "অম্ল", "class_level": 6}
    c.post("/learn/progress", headers=h, json={**base, "read_pct": 60})
    # bookmark-only update must not reset read_pct
    r = c.post("/learn/progress", headers=h, json={**base, "bookmarked": True})
    assert r.json()["bookmarked"] is True
    assert r.json()["read_pct"] == 60
    # completion update
    r = c.post("/learn/progress", headers=h, json={**base, "completed": True})
    assert r.json()["completed"] is True
    assert r.json()["bookmarked"] is True
    # still a single row (unique constraint)
    assert len(c.get("/learn/progress", headers=h).json()) == 1


def test_progress_filter_by_subject(tmp_path):
    c = _client(tmp_path)
    h = _register_login(c, "lp3@example.com")
    c.post(
        "/learn/progress",
        headers=h,
        json={"subject": "science", "chapter": "ক", "class_level": 6, "read_pct": 10},
    )
    c.post(
        "/learn/progress",
        headers=h,
        json={"subject": "bangla", "chapter": "খ", "class_level": 6, "read_pct": 10},
    )
    rows = c.get("/learn/progress?subject=science", headers=h).json()
    assert [r["chapter"] for r in rows] == ["ক"]


def test_read_pct_validation(tmp_path):
    c = _client(tmp_path)
    h = _register_login(c, "lp4@example.com")
    r = c.post(
        "/learn/progress",
        headers=h,
        json={"subject": "science", "chapter": "ক", "class_level": 6, "read_pct": 101},
    )
    assert r.status_code == 422


def test_teacher_cannot_write_progress(tmp_path):
    c = _client(tmp_path)
    h = _register_login(c, "lp5@example.com", role="teacher")
    r = c.post(
        "/learn/progress",
        headers=h,
        json={"subject": "science", "chapter": "ক", "class_level": 6, "read_pct": 10},
    )
    assert r.status_code == 403
    assert c.get("/learn/progress", headers=h).json() == []
