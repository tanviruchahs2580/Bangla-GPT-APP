"""SEC-01 (2026-11-20 audit): school-less teachers are not one tenancy.

F-04 anchored every teacher without a school to the shared default school, so
the default school acted as ONE tenancy for all of them. Anyone could
self-register as a teacher and list, read and act on the children another
standalone teacher had imported: roster, progress, activity, assignments,
short tests, weak matrix, coverage, and guardian-consent reconfirm. These
tests stand up two independent standalone teachers and prove each one sees
and touches only the classrooms they teach and the students enrolled there,
while the owner's own workflow keeps working.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    AuditLog,
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    School,
    Student,
    Teacher,
    User,
)
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers.assessment import _coverage_rooms
from bangla_gpt_api.routers.deps import _default_school_id, _standalone_room_ids
from bangla_gpt_api.routers.teacher_content import _assert_content_writable
from conftest import engine_url

SECRET = "test-secret-0123456789abcdef0123456789"
PASSWORD = "Isolation!2345"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test", database_url=engine_url(tmp_path, "isolation"), jwt_secret=SECRET
    )
    return TestClient(create_app(settings))


def _teacher(client: TestClient, email: str) -> dict:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "শিক্ষক", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _room_with_students(client: TestClient, headers: dict, section: str, csv_rows: str):
    room = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": section}, headers=headers
    )
    assert room.status_code == 201, room.text
    room_id = room.json()["id"]
    imported = client.post(
        f"/teacher/classrooms/{room_id}/import",
        json={"csv_text": f"name,email\n{csv_rows}"},
        headers=headers,
    )
    assert imported.status_code == 200, imported.text
    roster = client.get(f"/teacher/classrooms/{room_id}/roster", headers=headers)
    assert roster.status_code == 200, roster.text
    return room_id, [entry["student_id"] for entry in roster.json()]


def _coverage_room_ids(client: TestClient, email: str) -> list[int]:
    session = client.app.state.ctx.session_factory()
    try:
        user = session.execute(select(User).where(User.email == email)).scalar_one()
        return [room.id for room in _coverage_rooms(session, user)]
    finally:
        session.close()


@pytest.fixture
def two_teachers(client: TestClient):
    a = _teacher(client, "owner@isolation.test")
    room_a, kids_a = _room_with_students(
        client, a, "A", "Rahim, rahim@isolation.test\nKarima, karima@isolation.test\n"
    )
    b = _teacher(client, "stranger@isolation.test")
    return SimpleNamespace(a=a, b=b, room_a=room_a, kids_a=kids_a)


def test_owner_keeps_the_whole_standalone_workflow(client: TestClient, two_teachers) -> None:
    t = two_teachers
    assert len(t.kids_a) == 2
    rooms = client.get("/teacher/classrooms", headers=t.a).json()
    assert [r["id"] for r in rooms] == [t.room_a]
    students = client.get("/teacher/students", params={"class_level": 6}, headers=t.a).json()
    assert sorted(s["student_id"] for s in students) == sorted(t.kids_a)
    for sid in t.kids_a:
        assert client.get(f"/students/{sid}/progress", headers=t.a).status_code == 200
    matrix = client.get(
        "/teacher/weak-matrix", params={"class_level": 6, "room_id": t.room_a}, headers=t.a
    )
    assert matrix.status_code == 200
    assert client.get("/teacher/curriculum-coverage", headers=t.a).status_code == 200
    assert _coverage_room_ids(client, "owner@isolation.test") == [t.room_a]


def test_stranger_cannot_list_another_teachers_classes_or_children(
    client: TestClient, two_teachers
) -> None:
    t = two_teachers
    assert client.get("/teacher/classrooms", headers=t.b).json() == []
    assert client.get("/teacher/students", params={"class_level": 6}, headers=t.b).json() == []
    analytics = client.get("/teacher/classes/6/analytics", headers=t.b)
    assert analytics.status_code == 200
    assert analytics.json()["students"] == 0
    assert analytics.json()["students_detail"] == []
    grade_matrix = client.get("/teacher/weak-matrix", params={"class_level": 6}, headers=t.b)
    assert grade_matrix.status_code == 200
    assert {s["student_id"] for s in grade_matrix.json()["students"]}.isdisjoint(t.kids_a)
    coverage = client.get("/teacher/curriculum-coverage", headers=t.b).json()
    assert all(c["classroom_id"] != t.room_a for c in coverage["cells"])
    # The grid only renders cells for subjects with content, so check the
    # room set it is built from as well.
    assert _coverage_room_ids(client, "stranger@isolation.test") == []


@pytest.mark.parametrize(
    ("method", "path_template", "body_template"),
    [
        ("get", "/teacher/classrooms/{room}/roster", None),
        ("get", "/teacher/weak-matrix?class_level=6&room_id={room}", None),
        ("get", "/students/{kid}/progress", None),
        ("get", "/students/{kid}/activity", None),
        ("get", "/students/{kid}", None),
        ("get", "/students/{kid}/consent", None),
        ("post", "/students/{kid}/consent/reconfirm", {"accepted": True}),
        (
            "post",
            "/teacher/assignments",
            {
                "student_ids": ["{kid}"],
                "subject": "science",
                "chapter": "কোষ",
                "due_at": "2030-01-01T00:00:00Z",
            },
        ),
        ("post", "/teacher/support-plans", {"student_id": "{kid}"}),
        (
            "post",
            "/teacher/shorttests",
            {"classroom_id": "{room}", "subject": "science", "chapter": "কোষ"},
        ),
        (
            "post",
            "/teacher/classrooms/{room}/import",
            {"csv_text": "name,email\nX, x@isolation.test\n"},
        ),
        ("post", "/quizzes", {"student_id": "{kid}", "num_questions": 3}),
    ],
)
def test_stranger_is_answered_not_found_on_every_per_object_route(
    client: TestClient, two_teachers, method: str, path_template: str, body_template
) -> None:
    t = two_teachers
    kid, room = t.kids_a[0], t.room_a

    def fill(value):
        if isinstance(value, str):
            filled = value.replace("{kid}", str(kid)).replace("{room}", str(room))
            return int(filled) if filled.isdigit() else filled
        if isinstance(value, list):
            return [fill(v) for v in value]
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        return value

    path = fill(path_template)
    kwargs = {"headers": t.b}
    if body_template is not None:
        kwargs["json"] = fill(body_template)
    res = getattr(client, method)(path, **kwargs)
    # The same not-found shape as an id that was never issued (F-144), never
    # a 2xx and never a 403 that would confirm the object exists; and it is
    # the tenancy wall that answered (its code and its audit row), not
    # validation or a missing index.
    assert res.status_code == 404, (path, res.status_code, res.text)
    assert res.json()["detail"]["code"] in {"student_not_found", "classroom_not_found"}
    assert _denied_targets(client) & {f"student:{kid}", f"classroom:{room}"}


def _denied_targets(client: TestClient) -> set[str]:
    session = client.app.state.ctx.session_factory()
    try:
        return {
            row.target
            for row in session.execute(
                select(AuditLog).where(AuditLog.action == "cross_tenant_denied")
            ).scalars()
        }
    finally:
        session.close()


def test_denied_cross_teacher_touches_are_audited(client: TestClient, two_teachers) -> None:
    t = two_teachers
    assert client.get(f"/students/{t.kids_a[0]}/progress", headers=t.b).status_code == 404
    assert client.get(f"/teacher/classrooms/{t.room_a}/roster", headers=t.b).status_code == 404
    targets = _denied_targets(client)
    assert f"student:{t.kids_a[0]}" in targets
    assert f"classroom:{t.room_a}" in targets


def test_a_second_standalone_teacher_can_open_the_same_class_name(
    client: TestClient, two_teachers
) -> None:
    # Reviewer-found regression of the first SEC-01 draft: every standalone
    # room shared the default school's (school, level, section) key, so the
    # second teacher's "Class 6 A" was a 409 for a room they could not see.
    t = two_teachers
    res = client.post("/teacher/classrooms", json={"class_level": 6, "section": "A"}, headers=t.b)
    assert res.status_code == 201, res.text
    new_id = res.json()["id"]
    assert new_id != t.room_a
    assert [r["id"] for r in client.get("/teacher/classrooms", headers=t.b).json()] == [new_id]
    session = client.app.state.ctx.session_factory()
    try:
        homes = {
            room.id: session.get(School, room.school_id).code
            for room in session.execute(select(ClassRoom)).scalars()
        }
    finally:
        session.close()
    assert homes[t.room_a] != homes[new_id]
    assert all(code.startswith("BGPT-T") for code in homes.values())


def test_each_standalone_teacher_sees_only_their_own_class(
    client: TestClient, two_teachers
) -> None:
    t = two_teachers
    room_b, kids_b = _room_with_students(client, t.b, "B", "Nadia, nadia@isolation.test\n")
    b_students = client.get("/teacher/students", params={"class_level": 6}, headers=t.b).json()
    assert [s["student_id"] for s in b_students] == kids_b
    a_students = client.get("/teacher/students", params={"class_level": 6}, headers=t.a).json()
    assert sorted(s["student_id"] for s in a_students) == sorted(t.kids_a)
    assert client.get(f"/teacher/classrooms/{room_b}/roster", headers=t.a).status_code == 404
    assert client.get(f"/students/{kids_b[0]}/progress", headers=t.a).status_code == 404


def _user(session, email: str) -> User:
    return session.execute(select(User).where(User.email == email)).scalar_one()


def test_scope_rules_for_admins_school_staff_and_default_bound_accounts(
    client: TestClient, two_teachers
) -> None:
    session = client.app.state.ctx.session_factory()
    try:
        real = School(name="Real School", code="REAL-1")
        session.add(real)
        session.flush()
        bound = User(
            email="bound@isolation.test", role="teacher", password_hash="x", school_id=real.id
        )
        orphan_admin = User(email="orphan@isolation.test", role="school_admin", password_hash="x")
        platform = User(email="root@isolation.test", role="admin", password_hash="x")
        session.add_all([bound, orphan_admin, platform])
        session.commit()
        assert _standalone_room_ids(session, platform) is None
        assert _standalone_room_ids(session, bound) is None
        # A provisioning error must not inherit every standalone teacher's rooms.
        assert _standalone_room_ids(session, orphan_admin) == frozenset()
        # Binding an account to the default school must not reopen the shared
        # tenancy: it stays room-walled.
        default_id = _default_school_id(session)
        stranger = _user(session, "stranger@isolation.test")
        stranger.school_id = default_id
        session.commit()
        session.info.clear()
        assert _standalone_room_ids(session, stranger) == frozenset()
    finally:
        session.close()


def test_room_set_counts_legacy_default_rooms_but_never_a_real_school(
    client: TestClient, two_teachers
) -> None:
    t = two_teachers
    session = client.app.state.ctx.session_factory()
    try:
        default_id = _default_school_id(session)
        real = School(name="Real School", code="REAL-2")
        session.add(real)
        session.flush()
        stranger = _user(session, "stranger@isolation.test")
        profile = session.execute(
            select(Teacher).where(Teacher.user_id == stranger.id)
        ).scalar_one()
        legacy = ClassRoom(school_id=default_id, class_level=7, section="OLD")
        foreign = ClassRoom(school_id=real.id, class_level=7, section="X")
        session.add_all([legacy, foreign])
        session.flush()
        kid = Student(name="Foreign child", class_level=7)
        session.add(kid)
        session.flush()
        session.add_all(
            [
                ClassTeacher(classroom_id=legacy.id, teacher_id=profile.id, subject=""),
                ClassTeacher(classroom_id=foreign.id, teacher_id=profile.id, subject=""),
                ClassStudent(classroom_id=foreign.id, student_id=kid.id),
            ]
        )
        session.commit()
        rooms = _standalone_room_ids(session, stranger)
        legacy_id, foreign_id, kid_id = legacy.id, foreign.id, kid.id
    finally:
        session.close()
    assert rooms is not None and legacy_id in rooms and foreign_id not in rooms
    assert client.get(f"/teacher/classrooms/{legacy_id}/roster", headers=t.b).status_code == 200
    assert client.get(f"/students/{kid_id}/progress", headers=t.b).status_code == 404


def test_teacher_without_a_profile_still_owns_the_room_they_create(client: TestClient) -> None:
    headers = _teacher(client, "noprofile@isolation.test")
    session = client.app.state.ctx.session_factory()
    try:
        user = _user(session, "noprofile@isolation.test")
        session.query(Teacher).filter(Teacher.user_id == user.id).delete()
        session.commit()
    finally:
        session.close()
    res = client.post(
        "/teacher/classrooms", json={"class_level": 8, "section": "A"}, headers=headers
    )
    assert res.status_code == 201, res.text
    listed = client.get("/teacher/classrooms", headers=headers).json()
    assert [r["id"] for r in listed] == [res.json()["id"]]


class _Users:
    def __init__(self, *users: SimpleNamespace) -> None:
        self._by_id = {u.id: u for u in users}

    def get(self, _model, pk):
        return self._by_id.get(pk)


def test_school_less_teachers_cannot_overwrite_each_others_content() -> None:
    author = SimpleNamespace(id=1, role="teacher", school_id=None)
    stranger = SimpleNamespace(id=2, role="teacher", school_id=None)
    row = SimpleNamespace(created_by=1)
    db = _Users(author, stranger)
    _assert_content_writable(db, row, author)  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as denied:
        _assert_content_writable(db, row, stranger)  # type: ignore[arg-type]
    assert denied.value.status_code == 403
    # Inside a real school the school stays the tenancy (S-007 unchanged).
    colleague = SimpleNamespace(id=3, role="teacher", school_id=9)
    school_author = SimpleNamespace(id=4, role="teacher", school_id=9)
    _assert_content_writable(
        _Users(school_author, colleague), SimpleNamespace(created_by=4), colleague
    )  # type: ignore[arg-type]
