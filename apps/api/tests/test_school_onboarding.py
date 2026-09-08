"""S3.1 school onboarding: admin -> school code -> staff invite -> scoping."""

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JOIN_PASSWORD = "joinsecret9"


def make_client(tmp_path) -> tuple[TestClient, sqlite3.Connection]:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/school.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/school.db")
    return client, conn


@pytest.fixture
def env(tmp_path):
    client, conn = make_client(tmp_path)
    yield client, conn
    conn.close()


def _login(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _root(env) -> dict:
    client, _ = env
    return _login(client, "root@example.com")


def _make_school(env, name: str) -> dict:
    res = client_post_school(env, name)
    assert res.status_code == 201, res.text
    return res.json()


def client_post_school(env, name: str):
    client, _ = env
    return client.post("/admin/schools", json={"name": name}, headers=_root(env))


def _invite(env, school_id: int, role: str) -> dict:
    client, _ = env
    headers = _root(env)
    res = client.post(f"/schools/{school_id}/invites", json={"role": role}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _join(client: TestClient, code: str, email: str):
    return client.post(
        "/auth/join-school",
        json={
            "invite_code": code,
            "email": email,
            "password": JOIN_PASSWORD,
            "name": "শিক্ষিকা",
        },
    )


def test_admin_creates_school_with_safe_code(env) -> None:
    school = _make_school(env, "Anondo High School")
    assert school["name"] == "Anondo High School"
    assert re.fullmatch(r"[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}", school["code"])
    listed = client_get_schools(env)
    assert listed.status_code == 200
    assert [s["id"] for s in listed.json()] == [school["id"]]


def client_get_schools(env):
    client, _ = env
    return client.get("/admin/schools", headers=_root(env))


def test_invite_join_flow_single_use(env) -> None:
    client, conn = env
    school = _make_school(env, "Padma Academy")
    invite = _invite(env, school["id"], "teacher")
    assert invite["role"] == "teacher" and len(invite["code"]) == 10
    # only the hash is stored, never the plaintext code (R7)
    row = conn.execute(
        "SELECT code_hash, used_by FROM school_invites WHERE id=?", (invite["id"],)
    ).fetchone()
    assert row is not None and invite["code"] not in row[0]

    res = _join(client, invite["code"], "teacher1@padma.test")
    assert res.status_code == 201, res.text
    assert "access_token" in res.json()
    u = conn.execute(
        "SELECT role, school_id FROM users WHERE email='teacher1@padma.test'"
    ).fetchone()
    assert u == ("teacher", school["id"])
    # the issued token is valid (403 = authenticated; a plain teacher is not
    # a school staff-admin) and login with the chosen password works
    tok = _login(client, "teacher1@padma.test", JOIN_PASSWORD)
    assert client.get("/schools/mine", headers=tok).status_code == 403

    # single-use: second redemption rejected
    res2 = _join(client, invite["code"], "teacher2@padma.test")
    assert res2.status_code == 409 and res2.json()["detail"]["code"] == "code_used"
    # unknown code
    res3 = _join(client, "ZZZZZZZZZZ", "t3@padma.test")
    assert res3.status_code == 404 and res3.json()["detail"]["code"] == "invalid_code"
    # taken email (admin) with a fresh code
    invite2 = _invite(env, school["id"], "teacher")
    res4 = _join(client, invite2["code"], "root@example.com")
    assert res4.status_code == 409 and res4.json()["detail"]["code"] == "email_taken"


def test_school_admin_scoped_to_own_school(env) -> None:
    client, conn = env
    a = _make_school(env, "School A")
    b = _make_school(env, "School B")
    inv = _invite(env, a["id"], "school_admin")
    res = _join(client, inv["code"], "principal-a@school.test")
    assert res.status_code == 201
    headers = _login(client, "principal-a@school.test", JOIN_PASSWORD)

    # own school: invite + class registration allowed
    assert (
        client.post(
            f"/schools/{a['id']}/invites", json={"role": "teacher"}, headers=headers
        ).status_code
        == 201
    )
    room = client.post(
        f"/schools/{a['id']}/classes",
        json={"class_level": 6, "section": "green"},
        headers=headers,
    )
    assert room.status_code == 201, room.text
    assert room.json()["section"] == "GREEN"
    assert conn.execute(
        "SELECT school_id FROM classrooms WHERE id=?", (room.json()["id"],)
    ).fetchone() == (a["id"],)

    # other school: denied with explicit code
    denied = client.post(f"/schools/{b['id']}/invites", json={"role": "teacher"}, headers=headers)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "other_school"
    assert (
        client.post(
            f"/schools/{b['id']}/classes", json={"class_level": 9}, headers=headers
        ).status_code
        == 403
    )
    missing = client.post("/schools/9999/classes", json={"class_level": 9}, headers=headers)
    assert missing.status_code == 404

    # /schools/mine reports own school only
    mine = client.get("/schools/mine", headers=headers)
    assert mine.status_code == 200
    data = mine.json()
    assert data["school_id"] == a["id"] and data["code"] == a["code"]
    assert data["classrooms"] == 1 and data["students"] == 0
    assert [s["email"] for s in data["staff"]] == ["principal-a@school.test"]


def test_overview_rejects_plain_teachers_and_students(env) -> None:
    client, _ = env
    a = _make_school(env, "School C")
    inv = _invite(env, a["id"], "teacher")
    assert _join(client, inv["code"], "plain-teacher@school.test").status_code == 201
    teacher = _login(client, "plain-teacher@school.test", JOIN_PASSWORD)
    # teachers cannot manage invites or see the school overview
    assert client.get("/schools/mine", headers=teacher).status_code == 403
    assert (
        client.post(
            f"/schools/{a['id']}/invites", json={"role": "teacher"}, headers=teacher
        ).status_code
        == 403
    )
    # anonymous
    assert client.get("/schools/mine").status_code == 401


def test_school_admin_role_roundtrips_via_admin_role_update(env) -> None:
    client, _ = env
    res = client.post(
        "/auth/register",
        json={
            "email": "promote@school.test",
            "password": PASSWORD,
            "name": "নাম",
            "role": "teacher",
        },
    )
    assert res.status_code == 201
    uid = res.json()["user_id"]
    patched = client.patch(
        f"/admin/users/{uid}/role", json={"role": "school_admin"}, headers=_root(env)
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["role"] == "school_admin"


def test_classrooms_follow_the_teachers_school(env) -> None:
    client, conn = env
    a = _make_school(env, "School D")
    inv = _invite(env, a["id"], "teacher")
    assert _join(client, inv["code"], "roomteacher@school.test").status_code == 201
    headers = _login(client, "roomteacher@school.test", JOIN_PASSWORD)
    room = client.post("/teacher/classrooms", json={"class_level": 7}, headers=headers)
    assert room.status_code == 201, room.text
    school_id = conn.execute(
        "SELECT school_id FROM classrooms WHERE id=?", (room.json()["id"],)
    ).fetchone()[0]
    assert school_id == a["id"]

    # legacy school-less teacher keeps landing in the default school
    client.post(
        "/auth/register",
        json={"email": "legacy@school.test", "password": PASSWORD, "name": "নাম", "role": "teacher"},
    )
    legacy = _login(client, "legacy@school.test")
    room2 = client.post("/teacher/classrooms", json={"class_level": 8}, headers=legacy)
    assert room2.status_code == 201
    code = conn.execute(
        "SELECT s.code FROM classrooms c JOIN schools s ON s.id=c.school_id WHERE c.id=?",
        (room2.json()["id"],),
    ).fetchone()[0]
    assert code == "BGPT-DEFAULT"
