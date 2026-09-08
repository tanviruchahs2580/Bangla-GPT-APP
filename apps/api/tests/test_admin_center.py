"""S3.5 admin center: per-school stats, invite management, content versions."""

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
        database_url=f"sqlite:///{tmp_path}/adm.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/adm.db")
    yield client, conn
    conn.close()


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["access_token"]}


def _now() -> str:
    return str(datetime.now(UTC).replace(tzinfo=None))


def _seed(client: TestClient, conn: sqlite3.Connection) -> dict:
    """School + teacher + room + 2 students, one fresh and one old conversation."""
    root = _login(client, "root@example.com")
    school = client.post("/admin/schools", json={"name": "Adm School"}, headers=root).json()
    inv = client.post(
        f"/schools/{school['id']}/invites", json={"role": "teacher"}, headers=root
    ).json()
    res = client.post(
        "/auth/join-school",
        json={
            "invite_code": inv["code"],
            "email": "teach@adm.test",
            "password": JOIN_PASSWORD,
            "name": "Staff",
        },
    )
    assert res.status_code == 201, res.text
    teach = _login(client, "teach@adm.test", JOIN_PASSWORD)
    room = client.post("/teacher/classrooms", json={"class_level": 6}, headers=teach).json()
    csv_text = "K One,kone@adm.test\nK Two,ktwo@adm.test"
    res = client.post(
        f"/teacher/classrooms/{room['id']}/import", json={"csv_text": csv_text}, headers=teach
    )
    assert res.status_code == 200 and res.json()["created"] == 2
    sid = int(conn.execute("SELECT id FROM students WHERE name='K One'").fetchone()[0])
    conn.execute(
        "INSERT INTO conversations (student_id, title, last_strategy, created_at)"
        " VALUES (?, 'fresh', NULL, ?)",
        (sid, _now()),
    )
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=8)
    conn.execute(
        "INSERT INTO conversations (student_id, title, last_strategy, created_at)"
        " VALUES (?, 'old', NULL, ?)",
        (sid, str(old)),
    )
    conn.commit()
    return {"root": root, "teach": teach, "school": school}


def test_admin_school_stats_counts_aggregates(env) -> None:
    client, conn = env
    seeded = _seed(client, conn)
    root, school = seeded["root"], seeded["school"]
    # a second, empty school appears too (BGPT-DEFAULT backfill may exist)
    rows = client.get("/admin/schools/stats", headers=root).json()
    row = next(r for r in rows if r["id"] == school["id"])
    assert row["name"] == "Adm School"
    assert row["teachers"] == 1 and row["classrooms"] == 1 and row["students"] == 2
    assert row["sessions_7d"] == 1  # the 8-day-old conversation is excluded
    assert client.get("/admin/schools/stats", headers=seeded["teach"]).status_code == 403
    assert client.get("/admin/schools/stats").status_code == 401


def test_admin_invite_list_and_revoke(env) -> None:
    client, conn = env
    seeded = _seed(client, conn)
    root, school = seeded["root"], seeded["school"]
    sid = school["id"]
    # the invite used by join-school shows as redeemed; make one spare to revoke
    spare = client.post(f"/schools/{sid}/invites", json={"role": "teacher"}, headers=root).json()
    invites = client.get(f"/admin/schools/{sid}/invites", headers=root).json()
    assert len(invites) == 2
    assert {i["used"] for i in invites} == {True, False}
    assert "code" not in invites[0] and "code_hash" not in invites[0]  # R7: never returned
    used_row = next(i for i in invites if i["used"])
    res = client.delete(f"/admin/schools/{sid}/invites/{used_row['id']}", headers=root)
    assert res.status_code == 409
    res = client.delete(f"/admin/schools/{sid}/invites/{spare['id']}", headers=root)
    assert res.status_code == 204
    remaining = client.get(f"/admin/schools/{sid}/invites", headers=root).json()
    assert [i["id"] for i in remaining] == [used_row["id"]]
    # revoked code no longer redeems
    res = client.post(
        "/auth/join-school",
        json={
            "invite_code": spare["code"],
            "email": "late@adm.test",
            "password": JOIN_PASSWORD,
            "name": "Late",
        },
    )
    assert res.status_code == 404
    # unknown invite / unknown school / non-admin
    assert client.delete(f"/admin/schools/{sid}/invites/9999", headers=root).status_code == 404
    assert client.get("/admin/schools/424242/invites", headers=root).status_code == 404
    assert client.get(f"/admin/schools/{sid}/invites", headers=seeded["teach"]).status_code == 403
    assert client.get("/admin/schools/1/invites").status_code == 401


def test_admin_content_versions(env) -> None:
    client, conn = env
    seeded = _seed(client, conn)
    root = seeded["root"]
    uid = int(conn.execute("SELECT id FROM users WHERE email='root@example.com'").fetchone()[0])
    for version, source in ((1, "ai"), (2, "ai"), (3, "teacher")):
        conn.execute(
            "INSERT INTO chapter_contents (subject, class_level, chapter, version, source,"
            " payload, created_by, created_at) VALUES ('science', 6, 'chA', ?, ?, '{}', ?, ?)",
            (version, source, uid, _now()),
        )
    conn.execute(
        "INSERT INTO chapter_contents (subject, class_level, chapter, version, source,"
        " payload, created_by, created_at) VALUES ('math', 6, 'chB', 1, 'ai', '{}', NULL, ?)",
        (_now(),),
    )
    conn.commit()
    rows = client.get("/admin/content/versions", headers=root).json()
    assert [r["chapter"] for r in rows] == ["chB", "chA"]  # math < science ordering
    by_ch = {r["chapter"]: r for r in rows}
    assert by_ch["chA"] == {
        "subject": "science",
        "class_level": 6,
        "chapter": "chA",
        "current_version": 3,
        "versions_total": 3,
        "source": "teacher",
        "updated_at": by_ch["chA"]["updated_at"],
        "updated_by_email": "root@example.com",
    }
    assert by_ch["chB"]["current_version"] == 1
    assert by_ch["chB"]["versions_total"] == 1
    assert by_ch["chB"]["source"] == "ai"
    assert by_ch["chB"]["updated_by_email"] is None
    assert client.get("/admin/content/versions", headers=seeded["teach"]).status_code == 403
    assert client.get("/admin/content/versions").status_code == 401
