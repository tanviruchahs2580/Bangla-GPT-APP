"""S2.8: bulk assignment -- multi-student select, one quiz, due date, tracking."""

import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
# "kosh" -- class-6 NCTB science chapter present in the sample corpus
# (built from codepoints so the file stays pure ASCII on disk).
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)
BOGUS_CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9DF) + chr(0x9DF) + chr(0x9DF)
FUTURE = "2999-01-01T00:00:00Z"
PAST = "2000-01-01T00:00:00Z"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "assign.db"


@pytest.fixture
def client(db_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{db_path}",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register_teacher(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teacher", "role": "teacher"},
    )
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def teacher_headers(client: TestClient) -> dict[str, str]:
    return _register_teacher(client, "teach@example.com")


def _create_room(client: TestClient, headers: dict, level: int = 6, section: str = "A") -> int:
    res = client.post(
        "/teacher/classrooms",
        json={"class_level": level, "section": section},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _import_students(
    client: TestClient, headers: dict, room_id: int, n: int, prefix: str = "stu"
) -> list[str]:
    rows = "\n".join(f"{prefix.upper()} {i},{prefix}{i}@school.edu" for i in range(n))
    res = client.post(
        f"/teacher/classrooms/{room_id}/import",
        json={"csv_text": f"name,email\n{rows}"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return [r["invite_code"] for r in res.json()["rows"]]


def _student_ids(db_path, emails: list[str]) -> list[int]:
    conn = sqlite3.connect(db_path)
    try:
        marks = ",".join("?" * len(emails))
        found = {
            row[0]: row[1]
            for row in conn.execute(
                f"SELECT u.email, s.id FROM students s JOIN users u ON s.user_id = u.id "
                f"WHERE u.email IN ({marks})",
                emails,
            )
        }
    finally:
        conn.close()
    assert set(found) == set(emails), f"missing roster users: {set(emails) - set(found)}"
    return [found[e] for e in emails]


def _student_login(client: TestClient, email: str, code: str) -> dict[str, str]:
    """Invite-code first login, personal password, fresh token (as in S2.5)."""
    login = client.post("/auth/login", json={"email": email, "password": code})
    tok = login.json()["access_token"]
    change = client.post(
        "/auth/change-password",
        json={"current_password": code, "new_password": "studentpw1"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert change.status_code == 200, change.text
    res = client.post("/auth/login", json={"email": email, "password": "studentpw1"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _assign(
    client: TestClient,
    headers: dict,
    student_ids: list[int],
    *,
    chapter: str = CHAPTER,
    due_at: str = FUTURE,
):
    return client.post(
        "/teacher/assignments",
        json={
            "student_ids": student_ids,
            "subject": "science",
            "chapter": chapter,
            "num_questions": 5,
            "due_at": due_at,
        },
        headers=headers,
    )


def test_assign_52_students_fast_and_logged(client: TestClient, teacher_headers, caplog, db_path):
    """PASS-WHEN: 52-student assign pytest."""
    caplog.set_level(logging.INFO)
    rid = _create_room(client, teacher_headers)
    _import_students(client, teacher_headers, rid, 52)
    ids = _student_ids(db_path, [f"stu{i}@school.edu" for i in range(52)])
    assert len(ids) == 52

    res = _assign(client, teacher_headers, ids)
    assert res.status_code == 201, res.text
    body = res.json()
    assert len(body["attempts"]) == 52
    assert len({a["attempt_id"] for a in body["attempts"]}) == 52
    assert {a["student_id"] for a in body["attempts"]} == set(ids)
    assert 1 <= len(body["questions"]) <= 5

    logs = [r for r in caplog.records if "assignment_assigned" in r.getMessage()]
    assert logs, "assignment must log assignment_assigned with elapsed_ms"


def test_completion_list_correct(client: TestClient, teacher_headers, db_path):
    rid = _create_room(client, teacher_headers)
    codes = _import_students(client, teacher_headers, rid, 3)
    ids = _student_ids(db_path, [f"stu{i}@school.edu" for i in range(3)])

    res = _assign(client, teacher_headers, ids)
    assert res.status_code == 201, res.text
    aid = res.json()["id"]

    prog = client.get(f"/teacher/assignments/{aid}/progress", headers=teacher_headers)
    assert prog.status_code == 200
    rows = prog.json()
    assert len(rows) == 3
    assert all(r["done"] is False and r["overdue"] is False for r in rows)
    assert {r["student_id"] for r in rows} == set(ids)
    assert rows[0]["name"].startswith("STU")

    # student #0 sees the assignment and submits
    stu0 = _student_login(client, "stu0@school.edu", codes[0])
    mine = client.get("/assignments/mine", headers=stu0).json()
    assert len(mine) == 1 and mine[0]["attempt_id"] == next(
        a["attempt_id"] for a in res.json()["attempts"] if a["student_id"] == ids[0]
    )
    assert mine[0]["done"] is False and mine[0]["overdue"] is False
    graded = client.post(
        f"/quizzes/{mine[0]['attempt_id']}/submit",
        json={"answers": [0] * len(mine[0]["questions"])},
        headers=stu0,
    )
    assert graded.status_code == 200, graded.text

    rows = client.get(f"/teacher/assignments/{aid}/progress", headers=teacher_headers).json()
    by_sid = {r["student_id"]: r for r in rows}
    assert by_sid[ids[0]]["done"] is True
    assert by_sid[ids[0]]["score_pct"] == graded.json()["score_pct"]
    assert by_sid[ids[1]]["done"] is False and by_sid[ids[1]]["score_pct"] is None
    assert all(r["overdue"] is False for r in rows)  # due date is far future


def test_overdue_flag_only_for_unfinished(client: TestClient, teacher_headers, db_path):
    rid = _create_room(client, teacher_headers)
    codes = _import_students(client, teacher_headers, rid, 2)
    ids = _student_ids(db_path, [f"stu{i}@school.edu" for i in range(2)])

    res = _assign(client, teacher_headers, ids, due_at=PAST)
    aid = res.json()["id"]

    stu0 = _student_login(client, "stu0@school.edu", codes[0])
    mine = client.get("/assignments/mine", headers=stu0).json()
    assert mine[0]["overdue"] is True  # advisory flag for the student too
    client.post(
        f"/quizzes/{mine[0]['attempt_id']}/submit",
        json={"answers": [0] * len(mine[0]["questions"])},
        headers=stu0,
    )

    rows = client.get(f"/teacher/assignments/{aid}/progress", headers=teacher_headers).json()
    by_sid = {r["student_id"]: r for r in rows}
    assert by_sid[ids[0]]["done"] is True and by_sid[ids[0]]["overdue"] is False
    assert by_sid[ids[1]]["done"] is False and by_sid[ids[1]]["overdue"] is True


def test_validation_errors_and_scoping(client: TestClient, teacher_headers, db_path):
    rid = _create_room(client, teacher_headers)
    _import_students(client, teacher_headers, rid, 2)
    ids = _student_ids(db_path, ["stu0@school.edu", "stu1@school.edu"])

    # unknown student
    res = _assign(client, teacher_headers, ids + [99999])
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "unknown_student"

    # mixed class levels: one student from a class-9 room
    rid9 = _create_room(client, teacher_headers, level=9, section="A")
    _import_students(client, teacher_headers, rid9, 1, prefix="nine")
    nine_id = _student_ids(db_path, ["nine0@school.edu"])[0]
    res = _assign(client, teacher_headers, [ids[0], nine_id])
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "mixed_class_levels"

    # chapter without content
    res = _assign(client, teacher_headers, ids, chapter=BOGUS_CHAPTER)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "no_quiz_for_filter"

    # empty selection rejected by schema
    res = _assign(client, teacher_headers, [])
    assert res.status_code == 422

    # duplicate ids collapse to one attempt per student
    res = _assign(client, teacher_headers, [ids[0], ids[0]])
    assert res.status_code == 201
    assert len(res.json()["attempts"]) == 1

    # teacher list is owner-scoped; other teacher cannot read progress
    mine = client.get("/teacher/assignments", headers=teacher_headers).json()
    assert len(mine) == 1
    other = _register_teacher(client, "other@example.com")
    aid = mine[0]["id"]
    assert client.get("/teacher/assignments", headers=other).json() == []
    assert client.get(f"/teacher/assignments/{aid}/progress", headers=other).status_code == 404


def test_role_guards(client: TestClient, teacher_headers, db_path):
    rid = _create_room(client, teacher_headers)
    codes = _import_students(client, teacher_headers, rid, 1)
    ids = _student_ids(db_path, ["stu0@school.edu"])
    aid = _assign(client, teacher_headers, ids).json()["id"]

    stu0 = _student_login(client, "stu0@school.edu", codes[0])
    res = client.post(
        "/teacher/assignments",
        json={"student_ids": ids, "subject": "science", "chapter": CHAPTER, "due_at": FUTURE},
        headers=stu0,
    )
    assert res.status_code == 403
    assert client.get(f"/teacher/assignments/{aid}/progress", headers=stu0).status_code == 403
    assert client.get("/teacher/assignments", headers=stu0).status_code == 403
    # non-student roles see nothing in the student-facing list
    assert client.get("/assignments/mine", headers=teacher_headers).json() == []
    # anonymous
    assert client.post("/teacher/assignments", json={}).status_code == 401
