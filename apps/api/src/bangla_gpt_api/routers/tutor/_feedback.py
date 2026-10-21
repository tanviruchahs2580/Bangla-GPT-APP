"""Tutor routes, split by surface (C-03): the single-shot ask, the
conversation history, the streamed chat, feedback, and product events.

_feedback — C-03 split of ``routers/tutor.py``: same paths, same order, same
guards as the single module it came from.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from bangla_gpt_api.db.models import (
    ChatMessage,
    Conversation,
    Feedback,
    QuizAttempt,
    Student,
    User,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES, coded
from bangla_gpt_api.schemas import (
    FeedbackAdminRow,
    FeedbackOut,
    FeedbackQueuePage,
    FeedbackRequest,
    TriageUpdate,
)

from ..deps import (
    AdminUser,
    CurrentUser,
    DbSession,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)


@router.post(
    "/feedback",
    response_model=FeedbackOut,
    status_code=201,
    responses=coded(400, 403, 404),
)
def submit_feedback(payload: FeedbackRequest, db: DbSession, user: CurrentUser) -> FeedbackOut:
    # The "no target" case is a business rule, not a validation failure, so it
    # is a 400: 422 is reserved by FastAPI for request-model validation and its
    # documented body is an array of errors (AUD-0053 / API-02).
    if payload.message_id is None and payload.attempt_id is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "missing_target", "message": "message_id or attempt_id required"},
        )

    def _target_owner_user_id() -> int | None:
        """Resolve the account that owns the rated content (or None if gone)."""
        if payload.message_id is not None:
            conv_owner = db.scalar(
                select(Conversation.student_id)
                .join(ChatMessage, ChatMessage.conversation_id == Conversation.id)
                .where(ChatMessage.id == payload.message_id)
            )
            if conv_owner is None:
                return None
            return db.scalar(select(Student.user_id).where(Student.id == conv_owner))
        attempt_owner = db.scalar(
            select(QuizAttempt.student_id).where(QuizAttempt.id == payload.attempt_id)
        )
        if attempt_owner is None:
            return None
        return db.scalar(select(Student.user_id).where(Student.id == attempt_owner))

    owner_user_id = _target_owner_user_id()
    # Feedback attaches a user-written comment to someone else's chat message
    # or quiz attempt — restrict to the owner (admins may review anything).
    if owner_user_id is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "target_not_found", "message": "Rated content not found"},
        )
    if owner_user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail={"code": "not_owner", "message": "Not allowed to rate this content"},
        )

    row = Feedback(
        user_id=user.id,
        message_id=payload.message_id,
        attempt_id=payload.attempt_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    if payload.message_id is not None and payload.rating in (-1, 1):
        msg = db.get(ChatMessage, payload.message_id)
        if msg is not None:
            # Owner-only message rating (ownership already verified above).
            student_id = db.scalar(select(Student.id).where(Student.user_id == user.id))
            conv_owner_id = db.scalar(
                select(Conversation.student_id).where(Conversation.id == msg.conversation_id)
            )
            if student_id is not None and conv_owner_id == student_id:
                msg.rating = payload.rating
    db.add(row)
    db.commit()
    return FeedbackOut(status="recorded")


@router.get("/admin/feedback", response_model=FeedbackQueuePage)
def admin_feedback_queue(
    db: DbSession,
    admin: AdminUser,
    status: str = Query(default="open", pattern="^(open|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FeedbackQueuePage:
    """triage queue: oldest un-triaged feedback first. Rows carry
    the complaint and nothing more -- reporter identity beyond the id is
    deliberately withheld."""
    stmt = select(Feedback, User.role).join(User, User.id == Feedback.user_id)
    count_stmt = select(func.count()).select_from(Feedback)
    if status == "open":
        stmt = stmt.where(Feedback.triaged.is_(False))
        count_stmt = count_stmt.where(Feedback.triaged.is_(False))
    total = db.execute(count_stmt).scalar_one()
    open_count = db.execute(
        select(func.count()).select_from(Feedback).where(Feedback.triaged.is_(False))
    ).scalar_one()
    rows = db.execute(stmt.order_by(Feedback.id.asc()).limit(limit).offset(offset)).all()
    return FeedbackQueuePage(
        rows=[
            FeedbackAdminRow(
                id=fb.id,
                user_id=fb.user_id,
                role=role,
                rating=fb.rating,
                comment=fb.comment,
                message_id=fb.message_id,
                attempt_id=fb.attempt_id,
                triaged=fb.triaged,
                triaged_at=fb.triaged_at,
                note=fb.triage_note,
                created_at=fb.created_at,
            )
            for fb, role in rows
        ],
        total=total,
        open_count=open_count,
        limit=limit,
        offset=offset,
    )


@router.patch("/admin/feedback/{feedback_id}", response_model=FeedbackAdminRow)
def admin_feedback_triage(
    feedback_id: int, payload: TriageUpdate, db: DbSession, admin: AdminUser
) -> FeedbackAdminRow:
    """Mark a queue item triaged/un-triaged with an optional internal
    note. The note is admin-authored and never returned to end users."""
    fb = db.get(Feedback, feedback_id)
    if fb is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "feedback_not_found", "message": "Feedback not found"},
        )
    fb.triaged = payload.triaged
    fb.triaged_at = datetime.now(UTC).replace(tzinfo=None) if payload.triaged else None
    if payload.note is not None:
        fb.triage_note = payload.note
    db.commit()
    role = db.execute(select(User.role).where(User.id == fb.user_id)).scalar_one()
    return FeedbackAdminRow(
        id=fb.id,
        user_id=fb.user_id,
        role=role,
        rating=fb.rating,
        comment=fb.comment,
        message_id=fb.message_id,
        attempt_id=fb.attempt_id,
        triaged=fb.triaged,
        triaged_at=fb.triaged_at,
        note=fb.triage_note,
        created_at=fb.created_at,
    )
