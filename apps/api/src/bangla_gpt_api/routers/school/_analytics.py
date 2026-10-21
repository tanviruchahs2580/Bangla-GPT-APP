"""School coverage and trend analytics (aggregate, k-anonymity-safe).

C-03 split of ``routers/school.py``. ``school_coverage`` (radon CC 13) now
delegates one grade band at a time to ``_level_coverage``, so the per-band
queries and the "empty lists are honest no-signal" rule live in one readable
place. ``school_analytics`` keeps its documented write-on-GET analytics row
(the Dhaka-calendar window bound is explained inline).
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from bangla_gpt_api.db.models import (
    ChapterContent,
    ChapterProgress,
    ChatMessage,
    Conversation,
    DailyActivity,
    QuizAttempt,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import (
    SchoolActiveDay,
    SchoolAnalyticsOut,
    SchoolCoverageOut,
    SchoolCoverageRow,
)
from bangla_gpt_api.services.activity import dhaka_date

from ..common import _record_analytics
from ..deps import DbSession, SchoolStaffUser
from ._shared import _actor_school, _school_rooms, _school_students_by_room

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)


def _level_coverage(db: DbSession, level: int, level_students: list[int]) -> SchoolCoverageRow:
    """One grade band: what the library HAS vs what students practice."""
    content = db.execute(
        select(ChapterContent.subject, ChapterContent.chapter).where(
            ChapterContent.class_level == level
        )
    ).all()
    content_subjects = sorted({str(subject) for subject, _ in content})
    asked: set[str] = set()
    read = completed = 0
    if level_students:
        asked = {
            str(subject)
            for (subject,) in db.execute(
                select(QuizAttempt.subject)
                .where(
                    QuizAttempt.student_id.in_(level_students),
                    QuizAttempt.subject.is_not(None),
                )
                .distinct()
            ).all()
            if subject
        }
        read = int(
            db.execute(
                select(func.count(ChapterProgress.id)).where(
                    ChapterProgress.student_id.in_(level_students),
                    ChapterProgress.class_level == level,
                )
            ).scalar_one()
        )
        completed = int(
            db.execute(
                select(func.count(ChapterProgress.id)).where(
                    ChapterProgress.student_id.in_(level_students),
                    ChapterProgress.class_level == level,
                    ChapterProgress.completed.is_(True),
                )
            ).scalar_one()
        )
    return SchoolCoverageRow(
        class_level=level,
        content_subjects=content_subjects,
        asked_subjects=sorted(asked),
        uncovered_subjects=sorted(set(content_subjects) - asked),
        chapters_available=len({(s, c) for s, c in content}),
        chapters_read=read,
        chapters_completed=completed,
    )


@router.get("/school/coverage", response_model=SchoolCoverageOut)
def school_coverage(
    db: DbSession,
    user: SchoolStaffUser,
    school_id: Annotated[int | None, Query()] = None,
) -> SchoolCoverageOut:
    """Per grade the school runs: subjects the content library HAS versus
    the subjects this school's students actually practice, plus chapter
    read coverage. Empty lists are honest "no signal", never "covered".

    Practice proxy: ChatMessage rows carry no subject column, so asked
    subjects come from graded quiz attempts (documented deviation).
    """
    school = _actor_school(db, user, school_id)
    rooms = _school_rooms(db, school.id)
    students, _room_of = _school_students_by_room(db, [r.id for r in rooms])
    level_of = {s.id: s.class_level for s in students}
    rows: list[SchoolCoverageRow] = []
    for level in sorted({r.class_level for r in rooms}):
        level_students = [sid for sid, lvl in level_of.items() if lvl == level]
        rows.append(_level_coverage(db, level, level_students))
    return SchoolCoverageOut(rows=rows)


@router.get("/school/analytics", response_model=SchoolAnalyticsOut)
def school_analytics(
    db: DbSession,
    user: SchoolStaffUser,
    school_id: Annotated[int | None, Query()] = None,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> SchoolAnalyticsOut:
    """K-anonymity-safe trend counts only: daily actives, questions asked
    and quiz volume. No per-student row, no message content ever."""
    school = _actor_school(db, user, school_id)
    rooms = _school_rooms(db, school.id)
    students, _room_of = _school_students_by_room(db, [r.id for r in rooms])
    student_ids = [s.id for s in students]
    now = datetime.now(UTC).replace(tzinfo=None)
    since = now - timedelta(days=days)
    # DailyActivity.date is a Dhaka calendar day (services.activity.dhaka_date),
    # so the bound has to be one too. Deriving it from a UTC instant made the
    # window up to two days longer than `days` -- at 20:00 UTC, Dhaka "today" is
    # already the next calendar day -- which put more entries in active_by_date
    # than the caller asked for and diluted daily_active_avg below.
    since_day = dhaka_date(since)
    active_by_date: list[SchoolActiveDay] = []
    questions_asked = 0
    attempts = graded = 0
    avg_score: float | None = None
    if student_ids:
        for day, n in db.execute(
            select(DailyActivity.date, func.count(func.distinct(DailyActivity.student_id)))
            .where(
                DailyActivity.student_id.in_(student_ids),
                DailyActivity.date >= since_day,
            )
            .group_by(DailyActivity.date)
            .order_by(DailyActivity.date)
        ).all():
            active_by_date.append(SchoolActiveDay(date=str(day), students=int(n)))
        conv_ids = select(Conversation.id).where(Conversation.student_id.in_(student_ids))
        questions_asked = int(
            db.execute(
                select(func.count(ChatMessage.id)).where(
                    ChatMessage.conversation_id.in_(conv_ids),
                    ChatMessage.role == "user",
                    ChatMessage.created_at >= since,
                )
            ).scalar_one()
        )
        attempts = int(
            db.execute(
                select(func.count(QuizAttempt.id)).where(
                    QuizAttempt.student_id.in_(student_ids),
                    QuizAttempt.created_at >= since,
                )
            ).scalar_one()
        )
        graded, avg = db.execute(
            select(func.count(QuizAttempt.id), func.avg(QuizAttempt.score_pct)).where(
                QuizAttempt.student_id.in_(student_ids),
                QuizAttempt.status == "graded",
                QuizAttempt.score_pct.is_not(None),
                QuizAttempt.created_at >= since,
            )
        ).one()
        graded = int(graded)
        avg_score = round(float(avg), 2) if avg is not None else None
    _record_analytics(db, user.id, user.role, "school_analytics_viewed", {"days": days})
    db.commit()
    daily_active_avg = (
        round(sum(d.students for d in active_by_date) / len(active_by_date), 2)
        if active_by_date
        else 0.0
    )
    return SchoolAnalyticsOut(
        days=days,
        active_by_date=active_by_date,
        daily_active_avg=daily_active_avg,
        questions_asked=questions_asked,
        quiz_attempts=attempts,
        attempts_graded=graded,
        avg_quiz_score_pct=avg_score,
    )
