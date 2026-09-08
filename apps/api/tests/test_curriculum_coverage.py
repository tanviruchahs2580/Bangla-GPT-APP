"""S3.3 curriculum coverage grid endpoint (derivation unit tests: test_coverage.py)."""

import sqlite3
from datetime import UTC, datetime

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
        database_url=f"sqlite:///{tmp_path}/cov.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/cov.db")
    yield client, conn
    conn.close()


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["access_token"]}


def _join(client: TestClient, code: str, email: str) -> None:
    res = client.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": JOIN_PASSWORD, "name": "Staff"},
    )
    assert res.status_code == 201, res.text


def _now() -> str:
    return str(datetime.now(UTC).replace(tzinfo=None))


def _seed(client: TestClient, conn: sqlite3.Connection) -> tuple[dict, dict, dict, dict]:
    """One school, teacher, two rooms (6 GEN, 7), students, content, assignments, attempts."""
    root = _login(client, "root@example.com")
    school = client.post("/admin/schools", json={"name": "Cov School"}, headers=root).json()
    inv = client.post(
        f"/schools/{school['id']}/invites", json={"role": "teacher"}, headers=root
    ).json()
    _join(client, inv["code"], "teach@cov.test")
    teach = _login(client, "teach@cov.test", JOIN_PASSWORD)
    r1 = client.post("/teacher/classrooms", json={"class_level": 6}, headers=teach).json()
    r2 = client.post("/teacher/classrooms", json={"class_level": 7}, headers=teach).json()
    for room_id, names in ((r1["id"], ["K One", "K Two"]), (r2["id"], ["K Three"])):
        csv_text = "\n".join(f"{n},{n.lower().replace(' ', '')}@cov.test" for n in names)
        res = client.post(
            f"/teacher/classrooms/{room_id}/import", json={"csv_text": csv_text}, headers=teach
        )
        assert res.status_code == 200 and res.json()["created"] == len(names)

    def sid(name: str) -> int:
        return int(conn.execute("SELECT id FROM students WHERE name=?", (name,)).fetchone()[0])

    for subject, level, chapter in (
        ("science", 6, "ch1"),
        ("math", 6, "ch1"),
        ("science", 7, "ch1"),  # taught-only cell in room2
    ):
        conn.execute(
            "INSERT INTO chapter_contents (subject, class_level, chapter, version, source,"
            " payload, created_at) VALUES (?, ?, ?, 1, 'ai', '{}', ?)",
            (subject, level, chapter, _now()),
        )
    tid = int(
        conn.execute(
            "SELECT t.id FROM teachers t JOIN users u ON t.user_id = u.id"
            " WHERE u.email='teach@cov.test'"
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO class_teachers (classroom_id, teacher_id, subject, created_at)"
        " VALUES (?, ?, 'bangla', ?)",
        (r2["id"], tid, _now()),
    )
    # room1/6: science mastered (80+90), math practiced (40), english ungraded attempt
    for student, subject, status, pct in (
        ("K One", "science", "graded", 80.0),
        ("K One", "math", "graded", 40.0),
        ("K Two", "science", "graded", 90.0),
        ("K Two", "english", "open", None),
    ):
        total = 10
        conn.execute(
            "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total,"
            " correct, score_pct, quiz_json, created_at) VALUES (?, ?, 6, ?, ?, ?, ?, '[]', ?)",
            (
                sid(student),
                subject,
                status,
                total,
                int(((pct or 0) * total) / 100),
                pct,
                _now(),
            ),
        )
    conn.commit()
    return root, teach, r1, r2


def _cells(data: dict) -> dict[tuple[int, str], dict]:
    return {(c["classroom_id"], c["subject"]): c for c in data["cells"]}


def test_coverage_grid_statuses(env) -> None:
    client, conn = env
    _, teach, r1, r2 = _seed(client, conn)
    res = client.get("/teacher/curriculum-coverage", headers=teach)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["subjects"] == ["bangla", "english", "math", "science"]
    cells = _cells(data)
    sci = cells[(r1["id"], "science")]
    assert sci["status"] == "mastered" and sci["avg_score_pct"] == 85.0
    assert sci["taught"] and sci["attempts"] == 2 and sci["attempts_graded"] == 2
    assert sci["class_level"] == 6 and sci["section"] == "GEN"
    math_cell = cells[(r1["id"], "math")]
    assert math_cell["status"] == "practiced" and math_cell["avg_score_pct"] == 40.0
    eng = cells[(r1["id"], "english")]
    assert eng["status"] == "practiced" and eng["taught"] is False
    assert eng["attempts"] == 1 and eng["attempts_graded"] == 0 and eng["avg_score_pct"] is None
    # room2: content makes science taught-only; ClassTeacher('bangla') teaches bangla
    assert cells[(r2["id"], "science")]["status"] == "taught"
    ban = cells[(r2["id"], "bangla")]
    assert ban["status"] == "taught" and ban["taught"] and ban["attempts"] == 0
    # bangla has no content at class 6 -> no bangla cell for room1
    assert (r1["id"], "bangla") not in cells
    # room7 content does not leak into room6 cells
    assert cells[(r1["id"], "science")]["class_level"] == 6


def test_coverage_scoping_and_authz(env) -> None:
    client, conn = env
    root, teach, r1, _ = _seed(client, conn)
    # another school's teacher must not see this school's rooms and vice versa
    school2 = client.post("/admin/schools", json={"name": "Other Cov"}, headers=root).json()
    inv = client.post(
        f"/schools/{school2['id']}/invites", json={"role": "teacher"}, headers=root
    ).json()
    _join(client, inv["code"], "teach2@other.test")
    teach2 = _login(client, "teach2@other.test", JOIN_PASSWORD)
    other_room = client.post("/teacher/classrooms", json={"class_level": 8}, headers=teach2).json()
    mine = client.get("/teacher/curriculum-coverage", headers=teach2).json()
    assert mine["cells"] == []  # school2 has no content/assignments/attempts yet
    # admin sees every school's rooms
    admin = client.get("/teacher/curriculum-coverage", headers=root).json()
    admin_rooms = {c["classroom_id"] for c in admin["cells"]}
    assert r1["id"] in admin_rooms
    # (room8 has no subjects -> no cells; auth below is the point)
    assert other_room["id"] not in admin_rooms
    # plain student and anonymous are rejected
    assert client.get("/teacher/curriculum-coverage").status_code == 401
    # a parent token is not a teacher token
    par_reg = client.post(
        "/auth/register",
        json={"email": "par@cov.test", "password": PASSWORD, "role": "parent", "name": "Pa"},
    )
    assert par_reg.status_code == 201, par_reg.text
    par = _login(client, "par@cov.test")
    assert client.get("/teacher/curriculum-coverage", headers=par).status_code == 403
