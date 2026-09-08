"""S2.5: short tests -- class+chapter ultra-fast classroom-wide assignment."""

import json
import logging
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
# "kosh" -- a class-6 NCTB science chapter present in the sample corpus
# (built from codepoints so the file stays pure ASCII on disk).
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)
BOGUS_CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9DF) + chr(0x9DF) + chr(0x9DF)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "short.db"


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


def _create_room(client: TestClient, headers: dict, level: int = 6) -> int:
    res = client.post(
        "/teacher/classrooms",
        json={"class_level": level, "section": "A"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _import_students(client: TestClient, headers: dict, room_id: int, n: int) -> list[str]:
    rows = "\n".join(f"Student {i},stu{i}@school.edu" for i in range(n))
    res = client.post(
        f"/teacher/classrooms/{room_id}/import",
        json={"csv_text": f"name,email\n{rows}"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return [r["invite_code"] for r in res.json()["rows"]]


def _assign(
    client: TestClient,
    headers: dict,
    room_id: int,
    *,
    chapter: str = CHAPTER,
    duration_min: int = 10,
    num_questions: int = 5,
):
    return client.post(
        "/teacher/shorttests",
        json={
            "classroom_id": room_id,
            "subject": "science",
            "chapter": chapter,
            "num_questions": num_questions,
            "duration_min": duration_min,
        },
        headers=headers,
    )


def test_assign_whole_classroom_fast_and_logged(
    client: TestClient, teacher_headers, caplog
) -> None:
    caplog.set_level(logging.INFO)
    rid = _create_room(client, teacher_headers)
    _import_students(client, teacher_headers, rid, 5)
    started = time.perf_counter()
    res = _assign(client, teacher_headers, rid)
    wall_ms = (time.perf_counter() - started) * 1000
    assert res.status_code == 201, res.text
    body = res.json()
    assert 1 <= len(body["questions"]) <= 5
    assert len(body["attempts"]) == 5
    assert {a["attempt_id"] for a in body["attempts"]} == set(
        range(
            min(a["attempt_id"] for a in body["attempts"]),
            min(a["attempt_id"] for a in body["attempts"]) + 5,
        )
    )
    logs = [r for r in caplog.records if "shorttest_assigned" in r.getMessage()]
    assert logs, "assignment must log shorttest_assigned with elapsed_ms"
    logged = json.loads(logs[-1].getMessage())
    assert logged["students"] == 5
    # PASS-WHEN: generate->assign p95 <= 10s (single run far below target)
    assert logged["elapsed_ms"] < 10_000
    assert wall_ms < 10_000


def test_assign_rejects_empty_roster_and_unknown_room(client: TestClient, teacher_headers) -> None:
    rid = _create_room(client, teacher_headers)
    res = _assign(client, teacher_headers, rid)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "empty_roster"
    missing = _assign(client, teacher_headers, 999)
    assert missing.status_code == 404


def test_assign_chapter_without_content_422(client: TestClient, teacher_headers) -> None:
    rid = _create_room(client, teacher_headers)
    _import_students(client, teacher_headers, rid, 1)
    res = _assign(client, teacher_headers, rid, chapter=BOGUS_CHAPTER)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "no_quiz_for_filter"


def test_teacher_list_scoped_to_owner_and_classroom(client: TestClient, teacher_headers) -> None:
    rid = _create_room(client, teacher_headers)
    _import_students(client, teacher_headers, rid, 1)
    assert _assign(client, teacher_headers, rid).status_code == 201
    mine = client.get("/teacher/shorttests", headers=teacher_headers).json()
    assert len(mine) == 1 and mine[0]["classroom_id"] == rid
    assert (
        client.get(
            "/teacher/shorttests", params={"classroom_id": rid + 55}, headers=teacher_headers
        ).json()
        == []
    )
    other = _register_teacher(client, "other@example.com")
    assert client.get("/teacher/shorttests", headers=other).json() == []


def test_student_sees_assigned_test_and_can_submit(client: TestClient, teacher_headers) -> None:
    rid = _create_room(client, teacher_headers)
    codes = _import_students(client, teacher_headers, rid, 2)
    assigned = _assign(client, teacher_headers, rid).json()

    # invite-linked students must set a personal password before use
    login = client.post("/auth/login", json={"email": "stu0@school.edu", "password": codes[0]})
    tok = login.json()["access_token"]
    change = client.post(
        "/auth/change-password",
        json={"current_password": codes[0], "new_password": "studentpw1"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert change.status_code == 200, change.text
    res = client.post("/auth/login", json={"email": "stu0@school.edu", "password": "studentpw1"})
    student_hdr = {"Authorization": f"Bearer {res.json()['access_token']}"}

    mine = client.get("/shorttests/mine", headers=student_hdr).json()
    assert len(mine) == 1
    test = mine[0]
    assert test["chapter"] == CHAPTER and test["duration_min"] == 10
    assert test["expired"] is False and test["expires_at"] is not None
    assert test["attempt_id"] in {a["attempt_id"] for a in assigned["attempts"]}
    assert len(test["questions"]) == len(assigned["questions"])
    # every student in the class got their own attempt row
    ids = {a["attempt_id"] for a in assigned["attempts"]}
    assert len(ids) == len(assigned["attempts"]) == 2

    answers = [0] * len(test["questions"])
    graded = client.post(
        f"/quizzes/{test['attempt_id']}/submit",
        json={"answers": answers},
        headers=student_hdr,
    )
    assert graded.status_code == 200, graded.text
    assert graded.json()["total"] == len(test["questions"])


def test_mine_flags_expired_after_duration(client: TestClient, teacher_headers, db_path) -> None:
    rid = _create_room(client, teacher_headers)
    codes = _import_students(client, teacher_headers, rid, 1)
    assigned = _assign(client, teacher_headers, rid, duration_min=10).json()
    login = client.post("/auth/login", json={"email": "stu0@school.edu", "password": codes[0]})
    tok = login.json()["access_token"]
    client.post(
        "/auth/change-password",
        json={"current_password": codes[0], "new_password": "studentpw1"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    res = client.post("/auth/login", json={"email": "stu0@school.edu", "password": "studentpw1"})
    student_hdr = {"Authorization": f"Bearer {res.json()['access_token']}"}

    # roll the assignment back 3 hours at the storage layer (soft deadline)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE short_tests SET created_at = datetime(created_at, '-3 hours')")
    conn.commit()
    conn.close()

    mine = client.get("/shorttests/mine", headers=student_hdr).json()
    assert len(mine) == 1 and mine[0]["expired"] is True
    # expired is advisory: submitting after the window still grades
    graded = client.post(
        f"/quizzes/{assigned['attempts'][0]['attempt_id']}/submit",
        json={"answers": [0] * len(mine[0]["questions"])},
        headers=student_hdr,
    )
    assert graded.status_code == 200


def test_mine_empty_for_non_student(client: TestClient, teacher_headers) -> None:
    assert client.get("/shorttests/mine", headers=teacher_headers).json() == []
