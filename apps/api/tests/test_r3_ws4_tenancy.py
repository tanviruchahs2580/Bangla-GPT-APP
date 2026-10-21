"""B-08: the central ORM tenancy filter (read-path defense in depth).

Three layers are asserted here:

1. **Mechanism** -- a session carrying a tenant cannot select another
   school's ``Student``/``ClassRoom``/``ClassStudent`` rows through the ORM,
   including a database-backed ``Session.get()``; clearing the context (or
   never setting it) restores the unscoped behaviour jobs, CLIs and tests
   rely on; the deliberate bypass used by the tenancy helper shows the
   pre-image (that is what preserves 403 ``other_school`` instead of a bare
   404).
2. **Contract preservation** -- the routes that load-then-guard keep the
   documented status codes: cross-school teacher reads answer 403
   ``other_school``, unknown ids answer 404, and admin (platform-wide) reads
   still succeed.
3. **Scope** -- admin/student/parent sessions are not filtered.

The 66-test cross-school suites remain the behavioural backstop; this file
pins the mechanism itself so a future change to the filter is a deliberate
one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import ClassRoom, ClassStudent, School, Student
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.db.tenancy import (
    set_tenant_context,
    tenant_filter_bypassed,
    tenant_school_id,
)
from bangla_gpt_api.main import create_app

PASSWORD = "Str0ngRootPassw0rd!"
JOIN_PASSWORD = "Str0ngJoinPassw0rd!"
JWT = "test-secret-0123456789abcdef0123456789"


# --- 1. the mechanism ---------------------------------------------------------


class _Seeded:
    """Two schools, each with one classroom and one enrolled student."""

    def __init__(self, factory) -> None:
        self.factory = factory
        self.school_a = self._seed("School A", "A", 6, "শিক্ষার্থী-অ")
        self.school_b = self._seed("School B", "B", 7, "শিক্ষার্থী-ব")

    def _seed(self, name: str, code: str, level: int, student_name: str) -> dict:
        with self.factory() as s:
            school = School(name=name, code=code)
            s.add(school)
            s.flush()
            room = ClassRoom(school_id=school.id, class_level=level, section="GEN")
            s.add(room)
            s.flush()
            student = Student(name=student_name, class_level=level)
            s.add(student)
            s.flush()
            s.add(ClassStudent(classroom_id=room.id, student_id=student.id))
            s.commit()
            return {
                "school_id": school.id,
                "room_id": room.id,
                "student_id": student.id,
            }


@pytest.fixture
def seeded(tmp_path):
    settings = Settings(env="test", database_url=f"sqlite:///{tmp_path}/r3_ws4_tenant.db")
    engine = make_engine(settings)
    init_db(engine)
    return _Seeded(make_session_factory(engine))


def test_scoped_session_cannot_select_another_schools_rows(seeded: _Seeded) -> None:
    db = seeded.factory()
    try:
        set_tenant_context(db, seeded.school_a["school_id"])
        assert tenant_school_id(db) == seeded.school_a["school_id"]

        students = db.execute(select(Student)).scalars().all()
        assert [s.id for s in students] == [seeded.school_a["student_id"]]

        rooms = db.execute(select(ClassRoom)).scalars().all()
        assert [r.id for r in rooms] == [seeded.school_a["room_id"]]

        enrollments = db.execute(select(ClassStudent)).scalars().all()
        assert [e.student_id for e in enrollments] == [seeded.school_a["student_id"]]

        # A database-backed get is filtered too: the other school's row is
        # invisible even by primary key (the helper's explicit bypass below
        # is what keeps the 403 contract).
        assert db.get(Student, seeded.school_b["student_id"]) is None
        assert db.get(Student, seeded.school_a["student_id"]) is not None
    finally:
        db.close()


def test_clearing_or_never_setting_the_context_leaves_reads_unscoped(seeded: _Seeded) -> None:
    db = seeded.factory()
    try:
        # Never set: jobs, CLIs and pre-auth code see everything, as before.
        assert len(db.execute(select(Student)).scalars().all()) == 2

        set_tenant_context(db, seeded.school_a["school_id"])
        assert len(db.execute(select(Student)).scalars().all()) == 1

        set_tenant_context(db, None)
        assert tenant_school_id(db) is None
        assert len(db.execute(select(Student)).scalars().all()) == 2
    finally:
        db.close()


def test_the_bypass_sees_the_pre_image_for_the_tenancy_helper(seeded: _Seeded) -> None:
    """The one sanctioned bypass: a load immediately followed by the check."""
    db = seeded.factory()
    try:
        set_tenant_context(db, seeded.school_a["school_id"])
        other_id = seeded.school_b["student_id"]
        assert db.get(Student, other_id) is None
        with tenant_filter_bypassed(db):
            shown = db.get(Student, other_id)
        assert shown is not None and shown.id == other_id, (
            "the helper needs the pre-image to answer 403 other_school, not 404"
        )
        # The bypass is scoped to the context manager: query paths are
        # filtered again. (A repeat ``get`` would be served from the identity
        # map without a SELECT -- the documented caveat -- so the query path
        # is the one asserted here.)
        assert db.execute(select(Student).where(Student.id == other_id)).scalars().all() == []
    finally:
        db.close()


# --- 2. contract preservation at the route level ------------------------------


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/r3_ws4_tenant_api.db",
        jwt_secret=JWT,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


def _login(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["access_token"]}


def _register_student(client: TestClient, email: str, name: str = "শিক্ষার্থী") -> int:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": name,
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    return int(res.json()["profile_id"])


def _teacher_in_new_school(client: TestClient, name: str, teacher_email: str) -> dict:
    """Admin creates one school and a teacher attached to it."""
    root = _login(client, "root@example.com")
    school = client.post("/admin/schools", json={"name": name}, headers=root).json()
    invite = client.post(f"/schools/{school['id']}/invites", json={"role": "teacher"}, headers=root)
    assert invite.status_code == 201, invite.text
    joined = client.post(
        "/auth/join-school",
        json={
            "invite_code": invite.json()["code"],
            "email": teacher_email,
            "password": JOIN_PASSWORD,
            "name": "Teacher",
        },
    )
    assert joined.status_code == 201, joined.text
    return _login(client, teacher_email, JOIN_PASSWORD)


def test_cross_school_teacher_read_stays_403_other_school(client: TestClient) -> None:
    """The filter must not turn the documented refusal into an existence oracle."""
    other = _register_student(client, "b08-other@example.net")
    teacher = _teacher_in_new_school(client, "School A", "b08-teacher@school.test")

    denied = client.get(f"/students/{other}/progress", headers=teacher)
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["code"] == "other_school"


def test_unknown_student_is_still_404(client: TestClient) -> None:
    teacher = _teacher_in_new_school(client, "School B", "b08-teacher2@school.test")
    res = client.get("/students/999999/progress", headers=teacher)
    assert res.status_code == 404, res.text


def test_admin_reads_remain_platform_wide(client: TestClient) -> None:
    student = _register_student(client, "b08-admin-view@example.net")
    admin = _login(client, "root@example.com")
    res = client.get(f"/students/{student}/progress", headers=admin)
    assert res.status_code == 200, res.text


def test_same_school_teacher_read_succeeds(client: TestClient) -> None:
    """Isolation cannot be 'passed' by denying everyone."""
    root = _login(client, "root@example.com")
    school = client.post("/admin/schools", json={"name": "School C"}, headers=root).json()
    invite = client.post(f"/schools/{school['id']}/invites", json={"role": "teacher"}, headers=root)
    client.post(
        "/auth/join-school",
        json={
            "invite_code": invite.json()["code"],
            "email": "b08-inside@school.test",
            "password": JOIN_PASSWORD,
            "name": "Teacher",
        },
    )
    teacher = _login(client, "b08-inside@school.test", JOIN_PASSWORD)
    room = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "A"}, headers=teacher
    )
    assert room.status_code == 201, room.text
    room_id = room.json()["id"]

    # Enrol a student into the teacher's own classroom (CSV import creates
    # the account), then read that student's progress as the teacher.
    imported = client.post(
        f"/teacher/classrooms/{room_id}/import",
        json={"csv_text": "name,email\nশিক্ষার্থী,inside@example.net"},
        headers=teacher,
    )
    assert imported.status_code == 200, imported.text
    roster = client.get(f"/teacher/classrooms/{room_id}/roster", headers=teacher)
    assert roster.status_code == 200, roster.text
    student_id = roster.json()[0]["student_id"]

    ok = client.get(f"/students/{student_id}/progress", headers=teacher)
    assert ok.status_code == 200, ok.text
