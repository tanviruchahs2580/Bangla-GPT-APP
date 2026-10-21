"""Whole-school learning health (aggregate only).

C-03 split of ``routers/school.py``. ``school_health_overview`` used to be the
single most complex function in the router (radon CC 26); the cohort
resolution and the bucket/classification loop are now named helpers, so the
endpoint reads as what it is: resolve the school, size the cohort, bucket it.
Behaviour is unchanged -- the scope rules are the shared ``_actor_school``
(same 403/404 shapes) and the classification constants still come from
``services/atrisk.py``.
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from bangla_gpt_api.db.models import ClassRoom, Conversation, School, Student, User
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import SchoolAtRiskRow, SchoolHealthOut
from bangla_gpt_api.services import atrisk

from ..common import _attempt_percents
from ..deps import DbSession, SchoolStaffUser
from ._shared import SCHOOL_STRONG_AVG, _actor_school, _school_rooms, _school_students_by_room

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)


def _cohort(
    db: DbSession, school: School
) -> tuple[list[ClassRoom], list[Student], dict[int, ClassRoom]]:
    """Rooms, enrolled students (id order) and each student's room."""
    rooms = _school_rooms(db, school.id)
    students, room_of_int = _school_students_by_room(db, [r.id for r in rooms])
    room_by_id = {r.id: r for r in rooms}
    return rooms, students, {sid: room_by_id[rid] for sid, rid in room_of_int.items()}


def _staff_count(db: DbSession, school: School) -> int:
    return int(
        db.execute(
            select(func.count(User.id)).where(
                User.school_id == school.id, User.role.in_(["teacher", "school_admin"])
            )
        ).scalar_one()
    )


def _sessions_7d(db: DbSession, student_ids: list[int]) -> int:
    if not student_ids:
        return 0
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    return int(
        db.execute(
            select(func.count(Conversation.id)).where(
                Conversation.student_id.in_(student_ids),
                Conversation.created_at >= since,
            )
        ).scalar_one()
    )


def _bucket_cohort(
    students: list[Student],
    percents: dict[int, list[float]],
    room_of: dict[int, ClassRoom],
) -> tuple[int, int, int, int, list[SchoolAtRiskRow]]:
    """strong / support / risk / ungraded counts plus the at-risk rows."""
    strong = support = risk = ungraded = 0
    at_risk_rows: list[SchoolAtRiskRow] = []
    for student in students:
        scores = percents.get(student.id, [])
        avg = atrisk.avg_pct(scores)
        trend = atrisk.score_trend(scores)
        room = room_of.get(student.id)
        if avg is None:
            ungraded += 1
            continue
        if atrisk.is_at_risk(avg, trend):
            risk += 1
            at_risk_rows.append(
                SchoolAtRiskRow(
                    student_id=student.id,
                    name=student.name,
                    class_level=room.class_level if room else (student.class_level or 0),
                    section=room.section if room else "",
                    attempts_graded=len(scores),
                    avg_score_pct=avg,
                    trend=trend,
                )
            )
        elif avg >= SCHOOL_STRONG_AVG:
            strong += 1
        else:
            support += 1
    at_risk_rows.sort(key=lambda r: r.avg_score_pct if r.avg_score_pct is not None else 0.0)
    return strong, support, risk, ungraded, at_risk_rows


@router.get("/school/overview", response_model=SchoolHealthOut)
def school_health_overview(
    db: DbSession, user: SchoolStaffUser, school_id: int | None = Query(default=None)
) -> SchoolHealthOut:
    """Whole-school counts + strong/support/risk buckets + at-risk list.

    Aggregates only: buckets and averages over graded attempts; chat data
    contributes nothing beyond a count of sessions started in the last
    7 days (no message content ever leaves this endpoint).
    """
    school = _actor_school(db, user, school_id)
    rooms, students, room_of = _cohort(db, school)
    student_ids = [s.id for s in students]
    percents = _attempt_percents(db, student_ids)
    strong, support, risk, ungraded, at_risk_rows = _bucket_cohort(students, percents, room_of)
    graded = strong + support + risk

    def _pct(n: int) -> float:
        return round(100.0 * n / graded, 1) if graded else 0.0

    return SchoolHealthOut(
        school_id=school.id,
        name=school.name,
        code=school.code,
        students=len(students),
        teachers=_staff_count(db, school),
        classrooms=len(rooms),
        sessions_7d=_sessions_7d(db, student_ids),
        strong=strong,
        support=support,
        risk=risk,
        ungraded=ungraded,
        strong_pct=_pct(strong),
        support_pct=_pct(support),
        risk_pct=_pct(risk),
        at_risk=at_risk_rows,
    )
