"""S3.2 school dashboard: /school/overview aggregates must match the DB."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JOIN_PASSWORD = "joinsecret9"


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/dash.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/dash.db")
    yield client, conn
    conn.close()


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["access_token"]}


def _root(client: TestClient) -> dict:
    return _login(client, "root@example.com")


def _join(client: TestClient, code: str, email: str) -> None:
    res = client.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": JOIN_PASSWORD, "name": "Staff"},
    )
    assert res.status_code == 201, res.text


def _seed_school(env) -> tuple[dict, dict, dict]:
    """School with principal, teacher and two rooms; returns (headers, school, room ids)."""
    client, _ = env
    root = _root(client)
    school = client.post("/admin/schools", json={"name": "Dash School"}, headers=root).json()
    inv1 = client.post(
        f"/schools/{school['id']}/invites", json={"role": "school_admin"}, headers=root
    ).json()
    _join(client, inv1["code"], "prin@dash.test")
    inv2 = client.post(
        f"/schools/{school['id']}/invites", json={"role": "teacher"}, headers=root
    ).json()
    _join(client, inv2["code"], "teach@dash.test")
    teacher = _login(client, "teach@dash.test", JOIN_PASSWORD)
    room1 = client.post("/teacher/classrooms", json={"class_level": 6}, headers=teacher).json()
    prin = _login(client, "prin@dash.test", JOIN_PASSWORD)
    room2 = client.post(
        f"/schools/{school['id']}/classes", json={"class_level": 7}, headers=prin
    ).json()
    return prin, school, {"t": teacher, "r1": room1["id"], "r2": room2["id"]}


def _import_students(client: TestClient, headers: dict, room_id: int, names: list[str]) -> None:
    csv_text = "\n".join(f"{n},{n.lower().replace(' ', '')}@dash.test" for n in names)
    res = client.post(
        f"/teacher/classrooms/{room_id}/import", json={"csv_text": csv_text}, headers=headers
    )
    assert res.status_code == 200, res.text
    assert res.json()["created"] == len(names)


def _student_id(conn: sqlite3.Connection, name: str) -> int:
    return int(conn.execute("SELECT id FROM students WHERE name=?", (name,)).fetchone()[0])


def _attempt(conn: sqlite3.Connection, sid: int, pct: float, hours_ago: int) -> None:
    ts = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours_ago)
    conn.execute(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total, correct,"
        " score_pct, quiz_json, created_at) VALUES (?, 'science', 6, 'graded', 4, ?, ?, '[]', ?)",
        (sid, int(pct * 4 / 100), pct, str(ts)),
    )


def test_overview_aggregates_match_db(env) -> None:
    client, conn = env
    prin, school, rooms = _seed_school(env)
    _import_students(client, rooms["t"], rooms["r1"], ["S One", "S Two", "S Three", "S Four"])
    _import_students(client, rooms["t"], rooms["r2"], ["S Five", "S Six"])
    s = {
        n: _student_id(conn, n) for n in ["S One", "S Two", "S Three", "S Four", "S Five", "S Six"]
    }
    # strong: 85 avg | support: 57.5 | risk: 20 | ungraded | risk (room2) | strong: 75
    _attempt(conn, s["S One"], 90, 30)
    _attempt(conn, s["S One"], 80, 20)
    _attempt(conn, s["S Two"], 55, 30)
    _attempt(conn, s["S Two"], 60, 20)
    _attempt(conn, s["S Three"], 20, 20)
    _attempt(conn, s["S Five"], 30, 20)
    _attempt(conn, s["S Six"], 75, 20)
    # sessions: 2 recent + 1 old conversation for S One
    now = datetime.now(UTC).replace(tzinfo=None)
    for hours in (1, 24):
        conn.execute(
            "INSERT INTO conversations (student_id, title, last_strategy, created_at)"
            " VALUES (?, 't', NULL, ?)",
            (s["S One"], str(now - timedelta(hours=hours))),
        )
    conn.execute(
        "INSERT INTO conversations (student_id, title, last_strategy, created_at)"
        " VALUES (?, 'old', NULL, ?)",
        (s["S One"], str(now - timedelta(days=30))),
    )
    conn.commit()

    res = client.get("/school/overview", headers=prin)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["school_id"] == school["id"] and data["code"] == school["code"]
    assert data["students"] == 6
    assert data["teachers"] == 2  # principal + teacher
    assert data["classrooms"] == 2
    assert data["sessions_7d"] == 2  # the 30-day-old conversation is excluded
    assert (data["strong"], data["support"], data["risk"], data["ungraded"]) == (2, 1, 2, 1)
    assert data["strong_pct"] == 40.0 and data["support_pct"] == 20.0 and data["risk_pct"] == 40.0
    # cross-class at-risk list, worst first, carrying the room label
    at = data["at_risk"]
    assert [(r["name"], r["avg_score_pct"], r["section"]) for r in at] == [
        ("S Three", 20.0, "GEN"),
        ("S Five", 30.0, "GEN"),  # room2 was created without a section -> GEN
    ]
    assert at[1]["class_level"] == 7
    assert at[0]["attempts_graded"] == 1 and at[0]["trend"] == "flat"
    # R11: summary buckets only -- no message content fields ever appear
    assert "messages" not in str(data).lower()


def test_overview_authz_scoping(env) -> None:
    client, _ = env
    prin, school, rooms = _seed_school(env)
    # plain teacher (same school) may not read the dashboard
    assert client.get("/school/overview", headers=rooms["t"]).status_code == 403
    # anonymous
    assert client.get("/school/overview").status_code == 401
    # principal of ANOTHER school cannot target this one
    client2 = client
    root = _root(client2)
    other = client2.post("/admin/schools", json={"name": "Other School"}, headers=root).json()
    inv = client2.post(
        f"/schools/{other['id']}/invites", json={"role": "school_admin"}, headers=root
    ).json()
    _join(client2, inv["code"], "prin2@other.test")
    prin2 = _login(client2, "prin2@other.test", JOIN_PASSWORD)
    denied = client2.get(f"/school/overview?school_id={school['id']}", headers=prin2)
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "other_school"
    # their own school works (empty)
    empty = client2.get("/school/overview", headers=prin2)
    assert empty.status_code == 200 and empty.json()["students"] == 0
    # admin may read any school explicitly
    admin_view = client.get(f"/school/overview?school_id={school['id']}", headers=root)
    assert admin_view.status_code == 200
    assert admin_view.json()["students"] == 0
