"""SEC-01 follow-through: legacy default-school rooms get their owner back.

Rooms created before the B-07 ClassTeacher invariant have no assigned teacher,
so the SEC-01 room wall would leave them reachable only by a platform admin.
``scripts/backfill_standalone_room_owners.py`` infers the owner from recorded
work and assigns only unambiguous cases.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    School,
    ShortTest,
    Student,
    SupportPlan,
    Teacher,
    User,
)
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.routers.deps import _standalone_room_ids
from conftest import engine_url

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backfill_standalone_room_owners.py"
_spec = importlib.util.spec_from_file_location("backfill_standalone_room_owners", _SCRIPT)
assert _spec is not None and _spec.loader is not None
backfill = importlib.util.module_from_spec(_spec)
# dataclasses resolve their module through sys.modules
sys.modules[_spec.name] = backfill
_spec.loader.exec_module(backfill)


@pytest.fixture
def db(tmp_path):
    engine = make_engine(Settings(env="test", database_url=engine_url(tmp_path, "backfill")))
    init_db(engine)
    session = make_session_factory(engine)()
    try:
        yield session
    finally:
        session.close()


def _teacher(db, email: str, school_id: int | None = None) -> User:
    user = User(email=email, role="teacher", password_hash="x", school_id=school_id)
    db.add(user)
    db.flush()
    db.add(Teacher(user_id=user.id, name="T"))
    db.flush()
    return user


def _room(db, school_id: int, section: str, kids: int) -> tuple[ClassRoom, list[Student]]:
    room = ClassRoom(school_id=school_id, class_level=6, section=section)
    db.add(room)
    db.flush()
    students = []
    for i in range(kids):
        student = Student(name=f"S{section}{i}", class_level=6)
        db.add(student)
        db.flush()
        db.add(ClassStudent(classroom_id=room.id, student_id=student.id))
        students.append(student)
    db.flush()
    return room, students


def test_plans_and_applies_only_unambiguous_owners(db) -> None:
    default = School(name="Default School", code="BGPT-DEFAULT")
    real = School(name="Real School", code="REAL-1")
    db.add_all([default, real])
    db.flush()
    owner = _teacher(db, "owner@backfill.test")
    other = _teacher(db, "other@backfill.test")
    school_bound = _teacher(db, "bound@backfill.test", school_id=real.id)

    clear_room, _ = _room(db, default.id, "A", 2)  # short test by owner only
    db.add(
        ShortTest(classroom_id=clear_room.id, teacher_id=owner.id, subject="science", chapter="c")
    )
    split_room, split_kids = _room(db, default.id, "B", 2)  # two standalone teachers worked here
    db.add(SupportPlan(student_id=split_kids[0].id, teacher_id=owner.id, class_level=6))
    db.add(SupportPlan(student_id=split_kids[1].id, teacher_id=other.id, class_level=6))
    silent_room, silent_kids = _room(db, default.id, "C", 1)  # only a school-bound teacher's plan
    db.add(SupportPlan(student_id=silent_kids[0].id, teacher_id=school_bound.id, class_level=6))
    taught_room, _ = _room(db, default.id, "D", 1)  # already assigned: not an orphan
    owner_profile = db.query(Teacher).filter_by(user_id=owner.id).one()
    db.add(ClassTeacher(classroom_id=taught_room.id, teacher_id=owner_profile.id, subject=""))
    db.commit()

    plans = {p.classroom_id: p for p in backfill.plan_backfill(db)}
    assert set(plans) == {clear_room.id, split_room.id, silent_room.id}
    assert plans[clear_room.id].status == "single_candidate"
    assert plans[clear_room.id].evidence == {owner.id: ["short_test"]}
    assert plans[split_room.id].status == "ambiguous"
    assert plans[split_room.id].evidence == {owner.id: ["support_plan"], other.id: ["support_plan"]}
    # A school-bound teacher's work is never evidence for a standalone room.
    assert plans[silent_room.id].status == "no_evidence"
    assert plans[silent_room.id].evidence == {}

    # Nothing is assigned without an explicit, operator-confirmed pair: the
    # evidence shows who touched a room, which under SEC-01 any stranger could.
    assert backfill.apply_confirmed(db, list(plans.values()), {}) == []
    assert clear_room.id not in (_standalone_room_ids(db, owner) or set())

    results = backfill.apply_confirmed(
        db,
        list(plans.values()),
        {
            clear_room.id: owner.id,  # confirmed owner
            silent_room.id: other.id,  # owner with no evidence: allowed once confirmed
            split_room.id: school_bound.id,  # not a standalone teacher: refused
            taught_room.id: other.id,  # not an orphan: refused
        },
    )
    assert results == sorted(results, key=lambda line: int(line.split()[1].rstrip(":")))
    assert f"room {clear_room.id}: assigned to user {owner.id}" in results
    assert f"room {silent_room.id}: assigned to user {other.id}" in results
    assert any(line.startswith(f"room {split_room.id}: refused") for line in results)
    assert any(line.startswith(f"room {taught_room.id}: refused") for line in results)
    db.info.clear()  # new request, fresh scope cache
    assert clear_room.id in (_standalone_room_ids(db, owner) or set())
    assert silent_room.id in (_standalone_room_ids(db, other) or set())
    assert split_room.id not in (_standalone_room_ids(db, other) or set())


def test_cli_rejects_a_malformed_pair() -> None:
    with pytest.raises(SystemExit):
        backfill.main(["--assign", "12-34"])


def test_no_default_school_means_nothing_to_do(db) -> None:
    assert backfill.plan_backfill(db) == []
