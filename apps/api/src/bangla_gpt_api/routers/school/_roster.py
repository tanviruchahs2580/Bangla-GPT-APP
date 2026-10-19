"""School rosters: students (paginated), teachers, classrooms.

C-03 split of ``routers/school.py``. ``school_students`` (radon CC 16) had
three grouped queries and the page assembly inlined; the per-student signals
are now the ``_roster_signals`` helper and the endpoint reads as: scope, size,
page, decorate.

Privacy contract unchanged: id, name, grade, section, approximate last
activity and quiz-attempt count. NO email/phone ever.
"""

import logging
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from bangla_gpt_api.db.models import (
    ClassTeacher,
    DailyActivity,
    QuizAttempt,
    Teacher,
    User,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import (
    SchoolClassRow,
    SchoolStudentPage,
    SchoolStudentRow,
    SchoolTeacherRow,
)

from ..common import _attempt_percents
from ..deps import DbSession, SchoolStaffUser
from ._shared import _actor_school, _school_rooms, _school_students_by_room

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)


def _roster_signals(db: DbSession, ids: list[int]) -> tuple[dict[int, str], dict[int, int]]:
    """Last active day (max of activity day and last attempt) and attempt count.

    Three grouped queries for the whole page instead of three per student.
    "last_active" is the best honest signal available server-side.
    """
    last_day: dict[int, str] = {}
    attempts: dict[int, int] = {}
    if not ids:
        return last_day, attempts
    for sid, day in db.execute(
        select(DailyActivity.student_id, func.max(DailyActivity.date))
        .where(DailyActivity.student_id.in_(ids))
        .group_by(DailyActivity.student_id)
    ).all():
        last_day[sid] = str(day)
    for sid, ts in db.execute(
        select(QuizAttempt.student_id, func.max(QuizAttempt.created_at))
        .where(QuizAttempt.student_id.in_(ids))
        .group_by(QuizAttempt.student_id)
    ).all():
        if ts is None:
            # Unreachable per the model (created_at is NOT NULL), but
            # legacy SQLite rows may predate that constraint; skipping is
            # the safe response if one appears.
            continue  # type: ignore[unreachable]  # model says NOT NULL, but legacy SQLite rows can still carry NULL; skip defensively.
        iso = str(ts)[:10]
        if sid not in last_day or iso > last_day[sid]:
            last_day[sid] = iso
    for sid, n in db.execute(
        select(QuizAttempt.student_id, func.count())
        .where(QuizAttempt.student_id.in_(ids))
        .group_by(QuizAttempt.student_id)
    ).all():
        attempts[sid] = int(n)
    return last_day, attempts


@router.get("/school/students", response_model=SchoolStudentPage)
def school_students(
    db: DbSession,
    user: SchoolStaffUser,
    school_id: Annotated[int | None, Query()] = None,
    class_level: Annotated[int | None, Query(ge=1, le=12)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SchoolStudentPage:
    """Paginated school roster: id, name, grade, section, approximate last
    activity and quiz-attempt count. NO email/phone ever.
    """
    school = _actor_school(db, user, school_id)
    rooms = _school_rooms(db, school.id)
    students, room_of = _school_students_by_room(db, [r.id for r in rooms])
    room_by_id = {r.id: r for r in rooms}
    if class_level is not None:
        students = [s for s in students if s.class_level == class_level]
    total = len(students)
    page = students[offset : offset + limit]
    last_day, attempts = _roster_signals(db, [s.id for s in page])
    items = [
        SchoolStudentRow(
            student_id=s.id,
            name=s.name,
            class_level=s.class_level,
            section=room_by_id[room_of[s.id]].section if s.id in room_of else "GEN",
            last_active=last_day.get(s.id),
            quiz_attempts=attempts.get(s.id, 0),
        )
        for s in page
    ]
    return SchoolStudentPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/school/teachers", response_model=list[SchoolTeacherRow])
def school_teachers(
    db: DbSession,
    user: SchoolStaffUser,
    school_id: Annotated[int | None, Query()] = None,
) -> list[SchoolTeacherRow]:
    """Staff roster of the school: accounts with a teacher profile plus
    the subjects/classrooms they are assigned (ClassTeacher '' = all)."""
    school = _actor_school(db, user, school_id)
    staff = db.execute(
        select(User, Teacher)
        .join(Teacher, Teacher.user_id == User.id)
        .where(
            User.school_id == school.id,
            User.role.in_(["teacher", "school_admin"]),
        )
        .order_by(User.id)
    ).all()
    teacher_ids = [t.id for _, t in staff]
    subjects: dict[int, set[str]] = defaultdict(set)
    rooms: dict[int, set[int]] = defaultdict(set)
    if teacher_ids:
        for tid, cid, subject in db.execute(
            select(ClassTeacher.teacher_id, ClassTeacher.classroom_id, ClassTeacher.subject).where(
                ClassTeacher.teacher_id.in_(teacher_ids)
            )
        ).all():
            subjects[int(tid)].add(subject or "all")
            rooms[int(tid)].add(int(cid))
    return [
        SchoolTeacherRow(
            teacher_id=t.id,
            name=t.name,
            subjects=sorted(subjects.get(t.id, set())),
            classrooms=len(rooms.get(t.id, set())),
        )
        for _, t in staff
    ]


@router.get("/school/classes", response_model=list[SchoolClassRow])
def school_classes(
    db: DbSession,
    user: SchoolStaffUser,
    school_id: Annotated[int | None, Query()] = None,
) -> list[SchoolClassRow]:
    """Per classroom: enrollment, attempt volume and graded accuracy."""
    school = _actor_school(db, user, school_id)
    rooms = _school_rooms(db, school.id)
    students, room_of = _school_students_by_room(db, [r.id for r in rooms])
    percents = _attempt_percents(db, [s.id for s in students])
    counts: dict[int, list[float]] = defaultdict(lambda: [0, 0, 0, 0.0])
    for s in students:
        counts[room_of[s.id]][0] += 1
    # one grouped count + one grouped average instead of 2 queries/student
    ids = [s.id for s in students]
    if ids:
        for sid, n in db.execute(
            select(QuizAttempt.student_id, func.count())
            .where(QuizAttempt.student_id.in_(ids))
            .group_by(QuizAttempt.student_id)
        ).all():
            counts[room_of[int(sid)]][1] += int(n)
        for sid, pcts in percents.items():
            room_id = room_of[sid]
            counts[room_id][2] += len(pcts)
            counts[room_id][3] += sum(pcts)
    rows: list[SchoolClassRow] = []
    for r in rooms:
        students_n, att, graded, total_pct = counts[r.id]
        rows.append(
            SchoolClassRow(
                classroom_id=r.id,
                class_level=r.class_level,
                section=r.section,
                students=int(students_n),
                quiz_attempts=int(att),
                attempts_graded=int(graded),
                avg_quiz_accuracy=round(total_pct / graded, 2) if graded else None,
            )
        )
    return rows
