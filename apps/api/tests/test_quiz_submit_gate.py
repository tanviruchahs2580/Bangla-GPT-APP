"""B-07: submissions to a student's attempt are the student's own act.

``authorize_student_access`` is the read/write gate for progress and
profile surfaces -- in-school staff pass it for a student's data, and
nothing used to distinguish a progress READ from a teacher CHOOSING
ANSWERS on behalf of a student, silently moving the child out of the
at-risk bucket the weak-matrix, support plans, parent digests and
government reports all read.

The gate now splits at submissions:

* the owning student always may submit their own attempt;
* staff act only for the proctored roster: students with no login of
  their own (``students.user_id IS NULL`` -- the CSV paper flow) or the
  classroom's own assigned teacher (``ClassTeacher``, minted when a
  teacher creates the class) and school admins -- every proxy submission
  is audit-logged as ``quiz_proxy_submit``;
* a teacher from OUTSIDE the classroom (same school, someone else's
  roster) is a coded 403 -- that is the forgery case this gate exists
  for;
* self-registered students stay invisible to teachers entirely (the F-04
  wall answers ``student_not_found`` before this gate is reached, F-144).

Bengali literals are Unicode escapes only (house rule for API tests).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "submitgate"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str = "student") -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Test User", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login_headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _seed_classroom_student(client: TestClient, *, student_user_email: str | None) -> int:
    """One classroom owned+assigned to teach@example.com, one student in it.

    The classroom (+ its ClassTeacher assignment) comes from the real
    production path -- ``POST /teacher/classrooms`` mints the teacher link
    (B-07 companion invariant) and materialises the default school. The
    row-level student insert mirrors ``POST .../import``:
    ``student_user_email=None`` is the proctored paper roster
    (``students.user_id IS NULL``); an email attaches a real account.
    Seeding goes through the app's own session_factory so the test runs on
    BOTH engines (the Postgres parity lane runs the full domain suite).
    """
    from bangla_gpt_api.db.models import ClassStudent, Student, User

    teacher = _login_headers(client, "teach@example.com")
    room = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "A"}, headers=teacher
    )
    assert room.status_code == 201, room.text
    room_id = room.json()["id"]
    factory = client.app.state.ctx.session_factory
    with factory() as db, db.begin():
        if student_user_email is None:
            student = Student(name="Roster Student", class_level=6, user_id=None)
            db.add(student)
            db.flush()
        else:
            user = db.execute(select(User).where(User.email == student_user_email)).scalar_one()
            student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one()
        db.add(ClassStudent(classroom_id=room_id, student_id=student.id))
        student_id = student.id
    return int(student_id)


def _audit_proxy_rows(client: TestClient) -> list[dict]:
    admin_headers = _login_headers(client, "root@example.com")
    rows = client.get("/admin/audit", params={"action": "quiz_proxy_submit"}, headers=admin_headers)
    assert rows.status_code == 200, rows.text
    return rows.json()["rows"]


def test_teacher_outside_the_classroom_cannot_submit_forgery_case(
    client: TestClient,
) -> None:
    """The audit's harm scenario: same school, somebody else's roster."""
    _register(client, "teach@example.com", role="teacher")  # classroom owner
    _register(client, "other-teach@example.com", role="teacher")
    _register(client, "stu@example.com")  # account-holding classroom student
    student_id = _seed_classroom_student(client, student_user_email="stu@example.com")
    owner_headers = _login_headers(client, "teach@example.com")
    outsider_headers = _login_headers(client, "other-teach@example.com")

    started = client.post(
        "/quizzes",
        json={"student_id": student_id, "num_questions": 2},
        headers=owner_headers,
    )
    assert started.status_code == 200, started.text

    res = client.post(
        f"/quizzes/{started.json()['attempt_id']}/submit",
        json={"answers": [0] * len(started.json()["questions"])},
        headers=outsider_headers,
    )
    assert res.status_code == 403, res.text
    assert res.json()["detail"]["code"] == "staff_cannot_submit_student_quiz"
    # nothing was acted on: no proxy audit row was written by the refusal
    assert _audit_proxy_rows(client) == []


def test_assigned_teacher_submits_for_classroom_student_with_audit_row(
    client: TestClient,
) -> None:
    """The standing proctor feature: generate + grade inside the wall -- now
    with the privilege use in the audit trail."""
    _register(client, "teach@example.com", role="teacher")
    _register(client, "stu@example.com")
    student_id = _seed_classroom_student(client, student_user_email="stu@example.com")
    owner_headers = _login_headers(client, "teach@example.com")

    started = client.post(
        "/quizzes",
        json={"student_id": student_id, "num_questions": 2},
        headers=owner_headers,
    )
    assert started.status_code == 200, started.text
    res = client.post(
        f"/quizzes/{started.json()['attempt_id']}/submit",
        json={"answers": [0] * len(started.json()["questions"])},
        headers=owner_headers,
    )
    assert res.status_code == 200, res.text

    rows = _audit_proxy_rows(client)
    assert rows, "a staff-proxied submission must be audit-logged"
    assert rows[0]["detail"] == {
        "student_id": student_id,
        "attempt_id": started.json()["attempt_id"],
    }
    assert rows[0]["actor_role"] == "teacher"


def test_staff_may_submit_for_proctored_userless_student(client: TestClient) -> None:
    """CSV paper roster (``user_id IS NULL``): submitting IS the workflow."""
    _register(client, "teach@example.com", role="teacher")
    student_id = _seed_classroom_student(client, student_user_email=None)
    teacher_headers = _login_headers(client, "teach@example.com")

    started = client.post(
        "/quizzes",
        json={"student_id": student_id, "num_questions": 2},
        headers=teacher_headers,
    )
    assert started.status_code == 200, started.text
    res = client.post(
        f"/quizzes/{started.json()['attempt_id']}/submit",
        json={"answers": [0] * len(started.json()["questions"])},
        headers=teacher_headers,
    )
    assert res.status_code == 200, res.text
    assert _audit_proxy_rows(client)


def test_self_registered_student_stays_walled_from_teachers(
    client: TestClient,
) -> None:
    """F-04 unchanged: a self-registered student (no classroom) is outside
    every teacher's wall; the tenancy probe answers before this gate."""
    _register(client, "teach@example.com", role="teacher")
    student = _register(client, "lone@example.com")
    student_headers = _login_headers(client, "lone@example.com")
    teacher_headers = _login_headers(client, "teach@example.com")

    started = client.post(
        "/quizzes",
        json={"student_id": student["profile_id"], "num_questions": 2},
        headers=student_headers,
    )
    assert started.status_code == 200, started.text
    res = client.post(
        f"/quizzes/{started.json()['attempt_id']}/submit",
        json={"answers": [0] * len(started.json()["questions"])},
        headers=teacher_headers,
    )
    # F-144: the tenancy wall answers 404 student_not_found, the same
    # shape a nonexistent id gets.
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "student_not_found"
    # and the student's own submission is unaffected
    own = client.post(
        f"/quizzes/{started.json()['attempt_id']}/submit",
        json={"answers": [0] * len(started.json()["questions"])},
        headers=student_headers,
    )
    assert own.status_code == 200, own.text
