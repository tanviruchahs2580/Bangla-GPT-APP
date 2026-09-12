"""Parent Routes — split from the main.py god-module (ARCH-001).

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via :mod:`.deps`, shared helpers via :mod:`.common`.
"""

import logging
import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    AnswerLog,
    ChapterProgress,
    ChatMessage,
    Conversation,
    DailyActivity,
    Parent,
    ParentInvite,
    ParentStudentLink,
    QuizAttempt,
    Student,
    User,
)
from bangla_gpt_api.schemas import (
    EXPLANATION_STYLES,
    ActivityDay,
    ActivitySummary,
    ChapterStat,
    MemoryFactsOut,
    ParentInviteLinkRequest,
    ParentLinkRequest,
    ParentReportOut,
    StudentBrief,
    StudentPrefsOut,
    StudentPrefsPatch,
    StudentProgress,
    StudentResponse,
)
from bangla_gpt_api.services import (
    atrisk,
    parent_digest,
    weakness,
)
from bangla_gpt_api.services.activity import (
    dhaka_date,
    heatmap_days,
    streak_days,
)

from .common import (
    _answer_cells,
    _hash_invite,
    _record_analytics,
    _student_briefs,
    _student_profile,
    notify_user,
)
from .deps import (
    Ctx,
    CurrentUser,
    DbSession,
    ParentUser,
)

router = APIRouter()

logger = logging.getLogger(__name__)


@router.post("/parents/link", status_code=201)
def parent_link(
    app_ctx: Ctx, payload: ParentLinkRequest, db: DbSession, parent: ParentUser
) -> dict:
    """Legacy direct-ID linking — disabled by default (V2 hardening).

    An unconsented parent could previously link ANY student_id and read
    their progress. The invite-code flow (`/parents/link/invite`) is the
    consented path; enable ALLOW_DIRECT_PARENT_LINK only for migrations.
    """
    if not app_ctx.settings.allow_direct_parent_link:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "direct_link_disabled",
                "message": "Use the student's invite code via /parents/link/invite",
            },
        )
    parent_profile = db.execute(
        select(Parent).where(Parent.user_id == parent.id)
    ).scalar_one_or_none()
    if parent_profile is None:
        parent_profile = Parent(name=parent.email.split("@")[0], user_id=parent.id)
        db.add(parent_profile)
        db.flush()
    student = db.get(Student, payload.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    existing = db.execute(
        select(ParentStudentLink).where(
            ParentStudentLink.parent_id == parent_profile.id,
            ParentStudentLink.student_id == student.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Already linked")
    db.add(ParentStudentLink(parent_id=parent_profile.id, student_id=student.id))
    # Wave 1: both sides of a successful link are notified (the student
    # only when their profile is claimed by a user account).
    # Wave 2: each side is pointed at the screen they can actually open.
    notify_user(
        db,
        parent.id,
        "parent_link",
        "notif_parent_linked",
        {"student_id": student.id},
        link="/parent",
    )
    notify_user(
        db,
        student.user_id,
        "parent_link",
        "notif_parent_linked",
        {"student_id": student.id},
        link="/student/me",
    )
    try:
        db.commit()
    except IntegrityError as exc:
        # Lost a race against a concurrent duplicate link.
        db.rollback()
        raise HTTPException(status_code=409, detail="Already linked") from exc
    return {"linked": True, "parent_id": parent_profile.id, "student_id": student.id}


# ------------------------------------------------------------------
# Parent invite-code flow (C17): students generate a single-use code,
# parents redeem it. No more bare student_id guessing.
# ------------------------------------------------------------------


@router.post("/students/me/invite-code", status_code=201)
def create_parent_invite(app_ctx: Ctx, db: DbSession, user: CurrentUser) -> dict:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Students only")
    student = _student_profile(db, user)
    active = (
        db.execute(
            select(ParentInvite).where(
                ParentInvite.student_id == student.id,
                ParentInvite.used_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    active = [i for i in active if i.expires_at > now]
    for stale in active[2:]:  # keep at most 3 live codes per student
        db.delete(stale)
    code = "BGPT-" + secrets.token_hex(4).upper()
    db.add(
        ParentInvite(
            code_hash=_hash_invite(code),
            student_id=student.id,
            expires_at=now + timedelta(minutes=app_ctx.settings.invite_ttl_minutes),
        )
    )
    db.commit()
    return {"code": code, "expires_in_minutes": app_ctx.settings.invite_ttl_minutes}


# --- Wave 2: student learning preferences + memory --------------------------
# learning_prefs is a WHITELISTED dict; unknown keys are a hard 422 so no
# client can smuggle arbitrary state into the prompt path. The memory
# endpoints only ever expose facts DERIVED from real rows -- nothing the
# model "remembered" -- and DELETE is a soft opt-out (flag + cleared prefs),
# never a data-destroying surprise for the account owner.


@router.get("/students/me/prefs", response_model=StudentPrefsOut)
def get_my_prefs(db: DbSession, user: CurrentUser) -> StudentPrefsOut:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Students only")
    student = _student_profile(db, user)
    prefs = student.learning_prefs if isinstance(student.learning_prefs, dict) else {}
    return StudentPrefsOut(memory_enabled=bool(student.memory_enabled), learning_prefs=prefs)


@router.patch("/students/me/prefs", response_model=StudentPrefsOut)
def patch_my_prefs(payload: StudentPrefsPatch, db: DbSession, user: CurrentUser) -> StudentPrefsOut:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Students only")
    student = _student_profile(db, user)
    if payload.learning_prefs is not None:
        merged = dict(student.learning_prefs) if isinstance(student.learning_prefs, dict) else {}
        for key, value in payload.learning_prefs.items():
            if key == "explanation_style":
                if value not in EXPLANATION_STYLES:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "invalid_explanation_style",
                            "message": "explanation_style must be simple|standard|detailed",
                        },
                    )
                merged["explanation_style"] = value
            elif key == "subject_focus":
                if not isinstance(value, str) or not 1 <= len(value.strip()) <= 60:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "invalid_subject_focus",
                            "message": "subject_focus must be a 1-60 character string",
                        },
                    )
                merged["subject_focus"] = value.strip()
            else:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "unknown_learning_pref",
                        "message": f"Unsupported preference key: {key}",
                    },
                )
        student.learning_prefs = merged
    if payload.memory_enabled is not None:
        student.memory_enabled = payload.memory_enabled
    db.commit()
    db.refresh(student)
    prefs = student.learning_prefs if isinstance(student.learning_prefs, dict) else {}
    return StudentPrefsOut(memory_enabled=bool(student.memory_enabled), learning_prefs=prefs)


@router.get("/students/me/memory", response_model=MemoryFactsOut)
def get_my_memory(db: DbSession, user: CurrentUser) -> MemoryFactsOut:
    """The facts the tutor is allowed to personalize with -- all derived
    live from real rows (identity, graded quiz accuracy, prefs). Nothing
    here is generated copy."""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Students only")
    student = _student_profile(db, user)
    prefs = student.learning_prefs if isinstance(student.learning_prefs, dict) else {}
    cells = _answer_cells(db, [student.id]).get(student.id, {})
    weak = sorted(
        (
            chapter
            for chapter, (asked, correct) in cells.items()
            if (acc := atrisk.cell_accuracy(asked, correct)) is not None and acc < 60.0
        )
    )[:5]
    recent_subjects = [
        str(subject)
        for (subject,) in db.execute(
            select(QuizAttempt.subject)
            .where(
                QuizAttempt.student_id == student.id,
                QuizAttempt.subject.is_not(None),
            )
            .group_by(QuizAttempt.subject)
            .order_by(func.max(QuizAttempt.created_at).desc())
            .limit(5)
        ).all()
        if subject
    ]
    style = prefs.get("explanation_style")
    return MemoryFactsOut(
        memory_enabled=bool(student.memory_enabled),
        facts={
            "name": student.name,
            "class_level": student.class_level,
            "recent_subjects": recent_subjects,
            "weak_chapters": weak,
            "explanation_style": style if style in EXPLANATION_STYLES else None,
        },
    )


@router.delete("/students/me/memory", response_model=MemoryFactsOut)
def disable_my_memory(db: DbSession, user: CurrentUser) -> MemoryFactsOut:
    """Opt out: memory_enabled=false AND the stored learning preferences
    are cleared. Derived facts are never stored, so clearing the prefs is
    the complete deletion the owner asked for; the response says what the
    next personalized request will look like via the note code."""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Students only")
    student = _student_profile(db, user)
    student.memory_enabled = False
    student.learning_prefs = None
    db.commit()
    return MemoryFactsOut(
        memory_enabled=False,
        facts={},
        on_disable_note_code="memory_on_disable_note",
    )


@router.post("/parents/link/invite", status_code=201)
def link_via_invite(payload: ParentInviteLinkRequest, db: DbSession, parent: ParentUser) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None)
    invite = db.execute(
        select(ParentInvite).where(ParentInvite.code_hash == _hash_invite(payload.code))
    ).scalar_one_or_none()
    if invite is None or invite.used_at is not None or invite.expires_at < now:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_invite", "message": "Invalid or expired invite code"},
        )
    parent_profile = db.execute(
        select(Parent).where(Parent.user_id == parent.id)
    ).scalar_one_or_none()
    if parent_profile is None:
        parent_profile = Parent(name=parent.email.split("@")[0], user_id=parent.id)
        db.add(parent_profile)
        db.flush()
    existing = db.execute(
        select(ParentStudentLink).where(
            ParentStudentLink.parent_id == parent_profile.id,
            ParentStudentLink.student_id == invite.student_id,
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(ParentStudentLink(parent_id=parent_profile.id, student_id=invite.student_id))
        # Wave 1: a successful consented link notifies both sides.
        # Wave 2: per-role landing links (parent view vs student profile).
        linked_student = db.get(Student, invite.student_id)
        notify_user(
            db,
            parent.id,
            "parent_link",
            "notif_parent_linked",
            {"student_id": invite.student_id},
            link="/parent",
        )
        notify_user(
            db,
            linked_student.user_id if linked_student is not None else None,
            "parent_link",
            "notif_parent_linked",
            {"student_id": invite.student_id},
            link="/student/me",
        )
    invite.used_at = now
    invite.used_by_parent_id = parent_profile.id
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Already linked") from exc
    return {
        "linked": True,
        "parent_id": parent_profile.id,
        "student_id": invite.student_id,
    }


@router.get("/parents/me/children", response_model=list[StudentBrief])
def parent_children(db: DbSession, parent: ParentUser) -> list[StudentBrief]:
    parent_profile = db.execute(
        select(Parent).where(Parent.user_id == parent.id)
    ).scalar_one_or_none()
    if parent_profile is None:
        return []
    links = (
        db.execute(
            select(ParentStudentLink).where(ParentStudentLink.parent_id == parent_profile.id)
        )
        .scalars()
        .all()
    )
    if not links:
        return []
    students = (
        db.execute(select(Student).where(Student.id.in_([link.student_id for link in links])))
        .scalars()
        .all()
    )
    return _student_briefs(db, list(students))


@router.get("/parents/me/children/{student_id}/progress", response_model=StudentProgress)
def parent_child_progress(student_id: int, db: DbSession, parent: ParentUser) -> StudentProgress:
    parent_profile = db.execute(
        select(Parent).where(Parent.user_id == parent.id)
    ).scalar_one_or_none()
    if parent_profile is None:
        raise HTTPException(status_code=404, detail="Not linked to this student")
    link = db.execute(
        select(ParentStudentLink).where(
            ParentStudentLink.parent_id == parent_profile.id,
            ParentStudentLink.student_id == student_id,
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Not linked to this student")
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    attempts = (
        db.execute(select(QuizAttempt).where(QuizAttempt.student_id == student_id)).scalars().all()
    )
    graded = [a for a in attempts if a.status == "graded"]
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    if graded:
        rows = (
            db.execute(select(AnswerLog).where(AnswerLog.attempt_id.in_([a.id for a in graded])))
            .scalars()
            .all()
        )
        for row in rows:
            stats[row.chapter][0] += 1
            stats[row.chapter][1] += row.is_correct
    by_chapter = sorted(
        (
            ChapterStat(
                chapter=chapter,
                asked=asked,
                correct=correct_count,
                accuracy=round(100.0 * correct_count / asked, 2),
            )
            for chapter, (asked, correct_count) in stats.items()
        ),
        key=lambda s: s.accuracy,
    )
    weak_chapters = weakness.weak_names(db, student.id)
    avg_score = (
        round(sum(a.score_pct for a in graded if a.score_pct is not None) / len(graded), 2)
        if graded
        else None
    )
    return StudentProgress(
        student=StudentResponse(id=student.id, name=student.name, class_level=student.class_level),
        attempts_graded=len(graded),
        avg_score_pct=avg_score,
        by_chapter=by_chapter,
        weak_chapters=weak_chapters,
    )


# --- Wave 2: guardian activity + period report ------------------------------


def _linked_child(db: Session, parent: User, student_id: int) -> Student:
    """Guardian access = an explicit consented ParentStudentLink (C17);
    anything else is a 404, identical to the existing progress route."""
    parent_profile = db.execute(
        select(Parent).where(Parent.user_id == parent.id)
    ).scalar_one_or_none()
    if parent_profile is not None:
        link = db.execute(
            select(ParentStudentLink).where(
                ParentStudentLink.parent_id == parent_profile.id,
                ParentStudentLink.student_id == student_id,
            )
        ).scalar_one_or_none()
        if link is not None:
            student = db.get(Student, student_id)
            if student is not None:
                return student
    raise HTTPException(status_code=404, detail="Not linked to this student")


@router.get("/parents/me/children/{student_id}/activity", response_model=ActivitySummary)
def parent_child_activity(
    student_id: int,
    db: DbSession,
    parent: ParentUser,
    days: Annotated[int, Query(ge=7, le=370)] = 91,
) -> ActivitySummary:
    """Wave 2: the SAME activity summary the student sees on their own
    /students/{id}/activity, for one linked child (streak + Dhaka heatmap)."""
    _linked_child(db, parent, student_id)
    today = dhaka_date(datetime.now(UTC))
    rows = (
        db.execute(
            select(DailyActivity)
            .where(DailyActivity.student_id == student_id)
            .order_by(DailyActivity.date)
        )
        .scalars()
        .all()
    )
    window = heatmap_days(list(rows), today, days)
    date_axis = [
        (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=i)).date().isoformat()
        for i in range(days - 1, -1, -1)
    ]
    active = {r.date for r in rows if (r.questions or r.quizzes or r.minutes)}
    return ActivitySummary(
        streak=streak_days(active, today),
        today=today,
        days=[ActivityDay(date=d, **c) for d, c in zip(date_axis, window, strict=True)],
    )


def _window_report(db: Session, student: Student, period: str) -> ParentReportOut:
    """Wave 2: shared window-report math for parent + student views.

    DATA + suggestion CODE only; clients render the sentence (i18n).
    Single-source weakness rollup keeps this identical to the digest."""
    student_id = student.id
    window_days = 7 if period == "weekly" else 30
    now = datetime.now(UTC).replace(tzinfo=None)
    since = now - timedelta(days=window_days)
    attempts = (
        db.execute(
            select(QuizAttempt).where(
                QuizAttempt.student_id == student_id,
                QuizAttempt.created_at >= since,
                QuizAttempt.created_at <= now,
            )
        )
        .scalars()
        .all()
    )
    graded = [a for a in attempts if a.status == "graded" and a.score_pct is not None]
    percents = [float(a.score_pct or 0.0) for a in graded]
    avg_score = atrisk.avg_pct(percents)
    # window chapter accuracy (strengths inside the window)
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    if graded:
        for chapter, ok in db.execute(
            select(AnswerLog.chapter, AnswerLog.is_correct).where(
                AnswerLog.attempt_id.in_([a.id for a in graded])
            )
        ).all():
            stats[chapter][0] += 1
            stats[chapter][1] += int(ok)
    strengths = sorted(
        (
            chapter
            for chapter, (asked, correct) in stats.items()
            if asked and 100.0 * correct / asked >= 85.0
        ),
        key=lambda c: (-(stats[c][1] / stats[c][0]), c),
    )[:3]
    # Digest agreement: the exact rollup source the weekly e-mail uses.
    weak_chapters = [w.concept for w in weakness.weak_concepts(db, student_id)][
        : parent_digest.WEAK_CHAPTER_LIMIT
    ]
    conv_ids = select(Conversation.id).where(Conversation.student_id == student_id)
    questions_asked = int(
        db.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.conversation_id.in_(conv_ids),
                ChatMessage.role == "user",
                ChatMessage.created_at >= since,
            )
        ).scalar_one()
    )
    chapters_read = int(
        db.execute(
            select(func.count(ChapterProgress.id)).where(ChapterProgress.student_id == student_id)
        ).scalar_one()
    )
    chapters_completed = int(
        db.execute(
            select(func.count(ChapterProgress.id)).where(
                ChapterProgress.student_id == student_id,
                ChapterProgress.completed.is_(True),
            )
        ).scalar_one()
    )
    # Code + params only -- the client renders the sentence.
    params: dict[str, Any]
    if not attempts and questions_asked == 0:
        code, params = "sugg_no_activity", {}
    elif weak_chapters:
        code, params = "sugg_practice_weak", {"chapters": weak_chapters}
    elif avg_score is not None and avg_score >= 85.0:
        code, params = "sugg_keep_momentum", {"avg_score_pct": avg_score}
    else:
        code, params = "sugg_general_support", {}

    return ParentReportOut(
        student_id=student.id,
        name=student.name,
        class_level=student.class_level,
        period=period,
        window_start=since.isoformat(timespec="seconds"),
        window_end=now.isoformat(timespec="seconds"),
        quizzes_taken=len(attempts),
        quizzes_graded=len(graded),
        avg_score_pct=avg_score,
        chapters_read=chapters_read,
        chapters_completed=chapters_completed,
        questions_asked=questions_asked,
        weak_chapters=weak_chapters,
        strengths=strengths,
        suggestion_code=code,
        suggestion_params=params,
    )


@router.get("/parents/me/children/{student_id}/report", response_model=ParentReportOut)
def parent_child_report(
    student_id: int,
    db: DbSession,
    parent: ParentUser,
    period: Annotated[str, Query(pattern="^(weekly|monthly)$")] = "weekly",
) -> ParentReportOut:
    """Wave 2: JSON window report for one linked child.

    The server returns DATA + a suggestion CODE only; the final guardian-
    facing copy is rendered client-side (i18n). Weak chapters come from the
    same single-source weakness rollup the weekly digest uses, so the two
    views can never disagree; strengths are window chapter accuracy >= 85.
    """
    student = _linked_child(db, parent, student_id)
    report = _window_report(db, student, period)
    _record_analytics(db, parent.id, parent.role, "parent_report_viewed", {"period": period})
    db.commit()
    return report


@router.get("/students/me/report", response_model=ParentReportOut)
def student_self_report(
    db: DbSession,
    user: CurrentUser,
    period: Annotated[str, Query(pattern="^(weekly|monthly)$")] = "weekly",
) -> ParentReportOut:
    """Wave 2: same window report for the signed-in student (Me page)."""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Students only")
    student = _student_profile(db, user)
    return _window_report(db, student, period)


# S3.4: in-process weekly digest scheduler. Once per ISO week, Sunday
# ~22:00 Dhaka (digest_due owns the rule). The job reads ONLY aggregates
# (services.parent_digest); conversation content is never queried.
# S5.4: the once-per-week guard moved from a per-process dict into the
# job_runs ledger (jobs.claim_period), so N gunicorn workers can no
# longer double-send; with JOBS_BACKEND=arq the ARQ worker owns the
# schedule instead and these loops stay off.
