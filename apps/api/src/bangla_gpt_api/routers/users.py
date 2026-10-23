"""Users Routes — split from the main.py god-module.

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via:mod:`.deps`, shared helpers via:mod:`.common`.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import delete, func, or_, select, update

from bangla_gpt_api.auth.security import verify_password
from bangla_gpt_api.db.models import (
    AiJob,
    AiUsage,
    AnalyticsEventRow,
    AnswerLog,
    Assignment,
    AuditLog,
    ChapterContent,
    ChapterProgress,
    ChatMessage,
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    ConceptMastery,
    Conversation,
    DailyActivity,
    EmailVerification,
    Feedback,
    Notification,
    Parent,
    ParentInvite,
    ParentStudentLink,
    PasswordReset,
    QuestionBankEntry,
    QuestionPaper,
    QuizAttempt,
    RevisionItem,
    SavedNote,
    SchoolInvite,
    ShortTest,
    Student,
    StudentAbility,
    StudentInvite,
    SupportPlan,
    Teacher,
    TeacherDocument,
    User,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES, coded, message
from bangla_gpt_api.schemas import (
    AccountDeleteConfirm,
    ConsentReconfirmIn,
    ConsentStatusOut,
    DataExportResponse,
    MeResponse,
    StudentResponse,
)
from bangla_gpt_api.security import write_audit

from .deps import (
    CONSENT_VERSION,
    Ctx,
    CurrentUser,
    DbSession,
    _assert_student_in_school,
    _build_me_response,
    authorize_student_access,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)

#: Stable version of the export payload. v1 was the original six sections
#: (profile/attempts/links/conversations/messages/activity); v2 (S-021) adds
#: every remaining per-user table. Clients pin this key to detect shape
#: changes without diffing every list.
EXPORT_SCHEMA_VERSION = "2"


class _DataExportV2(DataExportResponse):
    """Export v2: the full per-user data set (S-021).

    The audit found the portability response omitted notes, notifications,
    chapter progress, revision items, the AI-usage ledger and analytics events
    -- all stored per user -- while ``DELETE /users/me`` cascaded through
    every one of them. A data subject received a partial answer to "what do
    you hold about me".

    Extending the schema in a local subclass keeps the served OpenAPI document
    honest (the versioned endpoint really returns these fields) without
    touching ``schemas.py``.

    Credential material is deliberately NOT exported: ``password_resets`` and
    ``email_verifications`` appear as metadata rows without their token
    hashes. Shared library artifacts (``chapter_contents`` authored by this
    account) are also out of scope -- they are not personal data once another
    school reads them -- and staff-only handling fields (feedback
    ``triage_note``) are omitted.
    """

    schema_version: str = EXPORT_SCHEMA_VERSION
    notes: list[dict] = Field(default_factory=list)
    notifications: list[dict] = Field(default_factory=list)
    chapter_progress: list[dict] = Field(default_factory=list)
    revision_items: list[dict] = Field(default_factory=list)
    concept_mastery: list[dict] = Field(default_factory=list)
    student_abilities: list[dict] = Field(default_factory=list)
    classrooms: list[dict] = Field(default_factory=list)
    ai_usage: list[dict] = Field(default_factory=list)
    analytics_events: list[dict] = Field(default_factory=list)
    feedback: list[dict] = Field(default_factory=list)
    ai_jobs: list[dict] = Field(default_factory=list)
    teacher_documents: list[dict] = Field(default_factory=list)
    question_papers: list[dict] = Field(default_factory=list)
    question_bank: list[dict] = Field(default_factory=list)
    short_tests: list[dict] = Field(default_factory=list)
    assignments: list[dict] = Field(default_factory=list)
    support_plans: list[dict] = Field(default_factory=list)
    parent_invites: list[dict] = Field(default_factory=list)
    student_invites: list[dict] = Field(default_factory=list)
    password_resets: list[dict] = Field(default_factory=list)
    email_verifications: list[dict] = Field(default_factory=list)
    audit_events: list[dict] = Field(default_factory=list)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@router.get("/users/me", response_model=MeResponse)
def read_me(app_ctx: Ctx, db: DbSession, user: CurrentUser) -> MeResponse:
    return _build_me_response(app_ctx, db, user)


@router.post("/users/me/sessions/revoke", status_code=204)
def revoke_my_sessions(db: DbSession, user: CurrentUser) -> Response:
    """Sign out EVERYWHERE (S-011): stamps the token epoch, so every
    outstanding bearer token of this account fails the F-05 epoch check on
    its next request. DB-backed, so it holds even when the shared cache is
    unreachable and survives restarts — the account-wide counterpart to
    POST /auth/logout (which ends exactly one session).
    """
    user.sessions_invalidated_at = datetime.now(UTC)
    write_audit(
        db,
        action="sessions_revoked",
        actor_user_id=user.id,
        actor_role=user.role,
        target=f"user:{user.id}",
        detail={},
    )
    db.commit()
    return Response(status_code=204)


@router.delete("/users/me", status_code=204, responses=coded(401, 409))
def delete_me(
    db: DbSession, user: CurrentUser, payload: AccountDeleteConfirm | None = None
) -> Response:
    """GDPR-style self-service account deletion.

    Removes the account and every row owned by it: student/teacher/parent
    profile and ALL FK-children (Postgres enforces referential integrity --
    SQLite silently does not, so every child table must be cleaned here or
    the delete aborts mid-transaction on the production engine). The last
    remaining admin cannot delete their own account (409).

    F-142: erasure is irreversible, so the CURRENT PASSWORD must be
    re-supplied in the body — a bearer token alone (possibly a stolen
    60-minute one) used to be enough to destroy the account permanently.
    A missing body or wrong password is a coded 401, the same contract as
    /auth/mfa/disable; a body-stripping intermediary therefore fails SAFE
    (no deletion), never open.
    """
    if payload is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "bad_current_password",
                "message": "Current password is required to delete this account",
            },
        )
    if user.role == "admin":
        admins = db.execute(
            select(func.count()).select_from(User).where(User.role == "admin")
        ).scalar_one()
        if admins <= 1:
            raise HTTPException(
                status_code=409,
                detail={"code": "last_admin_guard", "message": "Cannot delete the last admin"},
            )

    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    parent = db.execute(select(Parent).where(Parent.user_id == user.id)).scalar_one_or_none()
    teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()

    if parent is not None:
        db.execute(delete(ParentStudentLink).where(ParentStudentLink.parent_id == parent.id))
        # Redeemed invites keep their history; only the pointer to the
        # erased parent is dropped (nullable FK).
        db.execute(
            update(ParentInvite)
            .where(ParentInvite.used_by_parent_id == parent.id)
            .values(used_by_parent_id=None)
        )
        db.delete(parent)
    if teacher is not None:
        db.execute(delete(ClassTeacher).where(ClassTeacher.teacher_id == teacher.id))
        db.delete(teacher)
    if student is not None:
        attempt_ids = (
            db.execute(select(QuizAttempt.id).where(QuizAttempt.student_id == student.id))
            .scalars()
            .all()
        )
        if attempt_ids:
            db.execute(delete(AnswerLog).where(AnswerLog.attempt_id.in_(attempt_ids)))
        conv_ids = (
            db.execute(select(Conversation.id).where(Conversation.student_id == student.id))
            .scalars()
            .all()
        )
        if conv_ids:
            # F-093: feedback.message_id is a nullable FK into chat_messages.
            # Feedback written by ANY user against this student's answers
            # survived the delete below, so PostgreSQL raised
            # ForeignKeyViolation on feedback_message_id_fkey and the whole
            # erasure rolled back with a 500 — the data subject could not
            # exercise the right that exists precisely so they can leave.
            db.execute(
                update(Feedback)
                .where(
                    Feedback.message_id.in_(
                        select(ChatMessage.id).where(ChatMessage.conversation_id.in_(conv_ids))
                    )
                )
                .values(message_id=None)
            )
            db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conv_ids)))
        db.execute(delete(Conversation).where(Conversation.student_id == student.id))
        db.execute(
            # Same FK hazard on the attempt side: feedback on this student's
            # quiz attempts outlives the attempt row.
            update(Feedback)
            .where(Feedback.attempt_id.in_(attempt_ids or [-1]))
            .values(attempt_id=None)
        )
        db.execute(delete(QuizAttempt).where(QuizAttempt.student_id == student.id))
        db.execute(delete(ParentStudentLink).where(ParentStudentLink.student_id == student.id))
        db.execute(delete(ParentInvite).where(ParentInvite.student_id == student.id))
        # //+ S2/S4 children added after the original flow:
        # skipping any of these breaks deletion under Postgres (BUG-4).
        db.execute(delete(ChapterProgress).where(ChapterProgress.student_id == student.id))
        db.execute(delete(DailyActivity).where(DailyActivity.student_id == student.id))
        db.execute(delete(RevisionItem).where(RevisionItem.student_id == student.id))
        db.execute(delete(ClassStudent).where(ClassStudent.student_id == student.id))
        db.execute(delete(StudentInvite).where(StudentInvite.student_id == student.id))
        db.execute(delete(SupportPlan).where(SupportPlan.student_id == student.id))
        db.execute(delete(ConceptMastery).where(ConceptMastery.student_id == student.id))
        db.execute(delete(StudentAbility).where(StudentAbility.student_id == student.id))
        db.delete(student)

    # User-scoped rows (any role), removed before the users row itself.
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    db.execute(delete(EmailVerification).where(EmailVerification.user_id == user.id))
    db.execute(delete(Feedback).where(Feedback.user_id == user.id))
    db.execute(delete(QuestionPaper).where(QuestionPaper.teacher_id == user.id))
    db.execute(delete(ShortTest).where(ShortTest.teacher_id == user.id))
    db.execute(delete(Assignment).where(Assignment.teacher_id == user.id))
    db.execute(delete(QuestionBankEntry).where(QuestionBankEntry.teacher_id == user.id))
    db.execute(delete(SupportPlan).where(SupportPlan.teacher_id == user.id))
    # FK-children: teacher_documents, saved_notes, notifications
    # and ai_jobs must go before the users row (same BUG-4 rule).
    # analytics_events keeps its rows (append-only product trail) but loses
    # the attribution; see the update below.
    db.execute(delete(TeacherDocument).where(TeacherDocument.teacher_id == user.id))
    db.execute(delete(SavedNote).where(SavedNote.user_id == user.id))
    db.execute(delete(Notification).where(Notification.user_id == user.id))
    db.execute(delete(AiJob).where(AiJob.user_id == user.id))
    # AI-002 ledger rows go with the account (same BUG-4 rule).
    db.execute(delete(AiUsage).where(AiUsage.user_id == user.id))
    # F-058: the analytics trail has no FK to users by design ("it must never
    # block account deletion"), but nothing ever dropped the attribution
    # either, so after a successful erasure the row still carried user_id and
    # role for an account that no longer exists. Same policy as AuditLog: the
    # event survives, the pointer to the person does not.
    db.execute(
        update(AnalyticsEventRow).where(AnalyticsEventRow.user_id == user.id).values(user_id=None)
    )
    # Invites this account created go with it (redeemed staff links are
    # kept as evidence in the User row itself); redemption pointers to this
    # account are nulled.
    db.execute(delete(SchoolInvite).where(SchoolInvite.created_by == user.id))
    db.execute(update(SchoolInvite).where(SchoolInvite.used_by == user.id).values(used_by=None))
    # Shared artifacts survive their author, losing only the author pointer:
    db.execute(
        update(ChapterContent).where(ChapterContent.created_by == user.id).values(created_by=None)
    )
    # Audit rows are append-only and never deleted: the event survives the
    # account, only the attribution to an erased account is anonymised
    # (actor_user_id is nullable by design for exactly this erasure case).
    db.execute(update(AuditLog).where(AuditLog.actor_user_id == user.id).values(actor_user_id=None))

    db.delete(user)
    db.commit()
    return Response(status_code=204)


@router.get("/users/me/export", response_model=_DataExportV2)
def export_me(response: Response, db: DbSession, user: CurrentUser) -> _DataExportV2:
    """Self-service data portability: everything stored about this account."""
    response.headers["Content-Disposition"] = 'attachment; filename="my-data-export.json"'
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()
    parent = db.execute(select(Parent).where(Parent.user_id == user.id)).scalar_one_or_none()

    profile: dict
    attempt_rows: list[QuizAttempt] = []
    links: list[dict] = []
    if student is not None:
        profile = {
            "type": "student",
            "id": student.id,
            "name": student.name,
            "class_level": student.class_level,
            "consent_version": student.consent_version,
            "consent_at": student.consent_at.isoformat() if student.consent_at else None,
        }
        attempt_rows = list(
            db.execute(select(QuizAttempt).where(QuizAttempt.student_id == student.id)).scalars()
        )
        for link in db.execute(
            select(ParentStudentLink).where(ParentStudentLink.student_id == student.id)
        ).scalars():
            links.append({"direction": "linked_by", "parent_id": link.parent_id})
    elif teacher is not None:
        profile = {"type": "teacher", "id": teacher.id, "name": teacher.name}
    elif parent is not None:
        profile = {"type": "parent", "id": parent.id, "name": parent.name}
        for link in db.execute(
            select(ParentStudentLink).where(ParentStudentLink.parent_id == parent.id)
        ).scalars():
            links.append({"direction": "links", "student_id": link.student_id})
    else:
        profile = {"type": None}

    attempts = [
        {
            "id": a.id,
            "subject": a.subject,
            "class_level": a.class_level,
            "status": a.status,
            "total": a.total,
            "correct": a.correct,
            "score_pct": a.score_pct,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in attempt_rows
    ]
    # F-063: a student's export stopped at quiz scores. The conversations and
    # chat messages -- the largest body of personal data this product holds
    # about a child -- were not exported at all, so the "download everything
    # we hold about you" endpoint answered with a fraction of the truth.
    conversations: list[dict] = []
    chat_messages: list[dict] = []
    learning_activity: list[dict] = []
    if student is not None:
        conv_rows = list(
            db.execute(select(Conversation).where(Conversation.student_id == student.id)).scalars()
        )
        conv_ids = [c.id for c in conv_rows]
        conversations = [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in conv_rows
        ]
        if conv_ids:
            for m in (
                db.execute(select(ChatMessage).where(ChatMessage.conversation_id.in_(conv_ids)))
                .scalars()
                .all()
            ):
                chat_messages.append(
                    {
                        "conversation_id": m.conversation_id,
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                )
        learning_activity = [
            {
                "date": row.date,
                "questions": row.questions,
                "quizzes": row.quizzes,
                "minutes": row.minutes,
            }
            for row in (
                db.execute(select(DailyActivity).where(DailyActivity.student_id == student.id))
                .scalars()
                .all()
            )
        ]

    # audit event 2/5: data_export (self-service; only the fact is
    # logged -- the payload itself never touches logs or audit rows).
    write_audit(
        db,
        action="data_export",
        actor_user_id=user.id,
        actor_role=user.role,
        target=f"user:{user.id}",
        detail={"format": "json"},
    )
    db.commit()

    # --- S-021: the remaining per-user tables -------------------------------
    # Everything below is stored per user or per profile and was missing from
    # the export while DELETE /users/me removed it. Queried after the audit
    # write above so a failure changes nothing about the audit trail.
    notes = [
        {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "source": n.source,
            "source_ref": n.source_ref,
            "created_at": _iso(n.created_at),
        }
        for n in db.execute(select(SavedNote).where(SavedNote.user_id == user.id)).scalars()
    ]
    notifications = [
        {
            "id": n.id,
            "kind": n.kind,
            "code": n.code,
            "params": n.params,
            "link": n.link,
            "read_at": _iso(n.read_at),
            "created_at": _iso(n.created_at),
        }
        for n in db.execute(
            select(Notification).where(Notification.user_id == user.id).order_by(Notification.id)
        ).scalars()
    ]
    ai_usage = [
        {
            "id": row.id,
            "route": row.route,
            "model": row.model,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "estimated_cost_usd": row.estimated_cost_usd,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(AiUsage).where(AiUsage.user_id == user.id).order_by(AiUsage.id)
        ).scalars()
    ]
    analytics_events = [
        {
            "id": row.id,
            "name": row.name,
            "role": row.role,
            "props": row.props,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(AnalyticsEventRow)
            .where(AnalyticsEventRow.user_id == user.id)
            .order_by(AnalyticsEventRow.id)
        ).scalars()
    ]
    feedback_rows = [
        {
            "id": row.id,
            "rating": row.rating,
            "comment": row.comment,
            "message_id": row.message_id,
            "attempt_id": row.attempt_id,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(Feedback).where(Feedback.user_id == user.id).order_by(Feedback.id)
        ).scalars()
    ]
    ai_jobs = [
        {
            "id": row.id,
            "kind": row.kind,
            "status": row.status,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }
        for row in db.execute(
            select(AiJob).where(AiJob.user_id == user.id).order_by(AiJob.id)
        ).scalars()
    ]
    teacher_documents = [
        {
            "id": row.id,
            "kind": row.kind,
            "class_level": row.class_level,
            "subject": row.subject,
            "chapter": row.chapter,
            "title": row.title,
            "payload": row.payload,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(TeacherDocument)
            .where(TeacherDocument.teacher_id == user.id)
            .order_by(TeacherDocument.id)
        ).scalars()
    ]
    question_papers = [
        {
            "id": row.id,
            "class_level": row.class_level,
            "subject": row.subject,
            "exam_type": row.exam_type,
            "marks": row.marks,
            "status": row.status,
            "chapters": row.chapters,
            "questions": row.questions,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(QuestionPaper)
            .where(QuestionPaper.teacher_id == user.id)
            .order_by(QuestionPaper.id)
        ).scalars()
    ]
    question_bank = [
        {
            "id": row.id,
            "question_text": row.question_text,
            "options": row.options,
            "answer_index": row.answer_index,
            "subject": row.subject,
            "chapter": row.chapter,
            "class_level": row.class_level,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(QuestionBankEntry)
            .where(QuestionBankEntry.teacher_id == user.id)
            .order_by(QuestionBankEntry.id)
        ).scalars()
    ]
    short_tests = [
        {
            "id": row.id,
            "classroom_id": row.classroom_id,
            "subject": row.subject,
            "chapter": row.chapter,
            "num_questions": row.num_questions,
            "duration_min": row.duration_min,
            "attempts": row.attempts,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(ShortTest).where(ShortTest.teacher_id == user.id).order_by(ShortTest.id)
        ).scalars()
    ]
    assignments = [
        {
            "id": row.id,
            "subject": row.subject,
            "chapter": row.chapter,
            "num_questions": row.num_questions,
            "due_at": _iso(row.due_at),
            "attempts": row.attempts,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(Assignment).where(Assignment.teacher_id == user.id).order_by(Assignment.id)
        ).scalars()
    ]
    plan_filters = [SupportPlan.teacher_id == user.id]
    if student is not None:
        plan_filters.append(SupportPlan.student_id == student.id)
    support_plans = [
        {
            "id": row.id,
            "student_id": row.student_id,
            "class_level": row.class_level,
            "focus_concepts": row.focus_concepts,
            "plan": row.plan,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(SupportPlan).where(or_(*plan_filters)).order_by(SupportPlan.id)
        ).scalars()
    ]
    parent_invites: list[dict] = []
    student_invites: list[dict] = []
    if student is not None:
        parent_invites = [
            {
                "id": row.id,
                "expires_at": _iso(row.expires_at),
                "used_at": _iso(row.used_at),
                "created_at": _iso(row.created_at),
            }
            for row in db.execute(
                select(ParentInvite)
                .where(ParentInvite.student_id == student.id)
                .order_by(ParentInvite.id)
            ).scalars()
        ]
        student_invites = [
            {
                "id": row.id,
                "email": row.email,
                "classroom_id": row.classroom_id,
                "expires_at": _iso(row.expires_at),
                "used_at": _iso(row.used_at),
                "created_at": _iso(row.created_at),
            }
            for row in db.execute(
                select(StudentInvite)
                .where(StudentInvite.student_id == student.id)
                .order_by(StudentInvite.id)
            ).scalars()
        ]
    # Single-use credential rows: SHAPE only -- the token hashes are never
    # exported (they are derived secrets, not personal data).
    password_resets = [
        {
            "id": row.id,
            "expires_at": _iso(row.expires_at),
            "used_at": _iso(row.used_at),
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(PasswordReset).where(PasswordReset.user_id == user.id).order_by(PasswordReset.id)
        ).scalars()
    ]
    email_verifications = [
        {
            "id": row.id,
            "expires_at": _iso(row.expires_at),
            "used_at": _iso(row.used_at),
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(EmailVerification)
            .where(EmailVerification.user_id == user.id)
            .order_by(EmailVerification.id)
        ).scalars()
    ]
    audit_events = [
        {
            "id": row.id,
            "action": row.action,
            "target": row.target,
            "detail": row.detail,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(AuditLog).where(AuditLog.actor_user_id == user.id).order_by(AuditLog.id)
        ).scalars()
    ]

    # Student-scoped learning tables not covered by the v1 sections.
    chapter_progress: list[dict] = []
    revision_items: list[dict] = []
    concept_mastery: list[dict] = []
    student_abilities: list[dict] = []
    classrooms: list[dict] = []
    if student is not None:
        chapter_progress = [
            {
                "subject": row.subject,
                "chapter": row.chapter,
                "class_level": row.class_level,
                "read_pct": row.read_pct,
                "completed": row.completed,
                "bookmarked": row.bookmarked,
                "updated_at": _iso(row.updated_at),
            }
            for row in db.execute(
                select(ChapterProgress)
                .where(ChapterProgress.student_id == student.id)
                .order_by(ChapterProgress.id)
            ).scalars()
        ]
        revision_items = [
            {
                "id": row.id,
                "question": row.question,
                "options": row.options_json,
                "correct_index": row.correct_index,
                "chapter": row.chapter,
                "subject": row.subject,
                "class_level": row.class_level,
                "reps": row.reps,
                "interval_days": row.interval_days,
                "ease_factor": row.ease_factor,
                "due_date": row.due_date,
                "updated_at": _iso(row.updated_at),
            }
            for row in db.execute(
                select(RevisionItem)
                .where(RevisionItem.student_id == student.id)
                .order_by(RevisionItem.id)
            ).scalars()
        ]
        concept_mastery = [
            {
                "concept_id": row.concept_id,
                "correct": row.correct,
                "total": row.total,
                "updated_at": _iso(row.updated_at),
            }
            for row in db.execute(
                select(ConceptMastery)
                .where(ConceptMastery.student_id == student.id)
                .order_by(ConceptMastery.concept_id)
            ).scalars()
        ]
        student_abilities = [
            {
                "concept": row.concept,
                "class_level": row.class_level,
                "ability": row.ability,
                "attempts": row.attempts,
                "updated_at": _iso(row.updated_at),
            }
            for row in db.execute(
                select(StudentAbility)
                .where(StudentAbility.student_id == student.id)
                .order_by(StudentAbility.concept)
            ).scalars()
        ]
        classrooms = [
            {
                "classroom_id": room.id,
                "school_id": room.school_id,
                "class_level": room.class_level,
                "section": room.section,
            }
            for room in db.execute(
                select(ClassRoom)
                .join(ClassStudent, ClassStudent.classroom_id == ClassRoom.id)
                .where(ClassStudent.student_id == student.id)
                .order_by(ClassRoom.id)
            ).scalars()
        ]

    return _DataExportV2(
        schema_version=EXPORT_SCHEMA_VERSION,
        user={
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        profile=profile,
        quiz_attempts=attempts,
        parent_links=links,
        conversations=conversations,
        chat_messages=chat_messages,
        learning_activity=learning_activity,
        notes=notes,
        notifications=notifications,
        chapter_progress=chapter_progress,
        revision_items=revision_items,
        concept_mastery=concept_mastery,
        student_abilities=student_abilities,
        classrooms=classrooms,
        ai_usage=ai_usage,
        analytics_events=analytics_events,
        feedback=feedback_rows,
        ai_jobs=ai_jobs,
        teacher_documents=teacher_documents,
        question_papers=question_papers,
        question_bank=question_bank,
        short_tests=short_tests,
        assignments=assignments,
        support_plans=support_plans,
        parent_invites=parent_invites,
        student_invites=student_invites,
        password_resets=password_resets,
        email_verifications=email_verifications,
        audit_events=audit_events,
    )


@router.get("/students/{student_id}", response_model=StudentResponse)
def get_student(student_id: int, db: DbSession, user: CurrentUser) -> StudentResponse:
    student = authorize_student_access(db, student_id, user)
    return StudentResponse(id=student.id, name=student.name, class_level=student.class_level)


@router.get("/students/{student_id}/consent", response_model=ConsentStatusOut)
def get_consent_status(student_id: int, db: DbSession, user: CurrentUser) -> ConsentStatusOut:
    """is the stored guardian consent current for this student?"""
    student = authorize_student_access(db, student_id, user)
    return ConsentStatusOut(
        student_id=student.id,
        current_version=CONSENT_VERSION,
        accepted_version=student.consent_version,
        accepted_at=student.consent_at,
        needs_reconfirm=student.consent_version != CONSENT_VERSION,
    )


@router.post(
    "/students/{student_id}/consent/reconfirm",
    response_model=ConsentStatusOut,
    responses={**coded(400), **message(403, 404)},
)
def post_consent_reconfirm(
    student_id: int,
    payload: ConsentReconfirmIn,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ConsentStatusOut:
    """re-confirm flow: student or linked guardian accepts the
    CURRENT consent text; evidence trail (at/ip/version) is refreshed."""
    if not payload.accepted:
        raise HTTPException(
            status_code=400,
            detail={"code": "consent_not_accepted", "message": "acceptance required"},
        )
    # align implementation with policy "student or linked guardian"
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(
            status_code=404, detail={"code": "student_not_found", "message": "Student not found"}
        )
    allowed = False
    if user.role == "student" and student.user_id == user.id:
        allowed = True
    elif user.role == "parent":
        parent = db.execute(select(Parent).where(Parent.user_id == user.id)).scalar_one_or_none()
        if parent is not None:
            link = db.execute(
                select(ParentStudentLink).where(
                    ParentStudentLink.parent_id == parent.id,
                    ParentStudentLink.student_id == student.id,
                )
            ).scalar_one_or_none()
            if link is not None:
                allowed = True
    elif user.role in ("admin", "teacher", "school_admin"):
        # Staff support path: teacher/school_admin stay behind the school
        # tenancy wall (same gate as GET /students/{id}/consent); admin is
        # platform-wide by design.
        if user.role != "admin":
            _assert_student_in_school(db, user, student)
        allowed = True
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={"code": "not_allowed", "message": "Not allowed to access this student"},
        )
    # reuse student already loaded
    student.consent_version = CONSENT_VERSION
    student.consent_at = datetime.now(UTC)
    student.consent_ip = request.client.host if request.client else None
    db.commit()
    return ConsentStatusOut(
        student_id=student.id,
        current_version=CONSENT_VERSION,
        accepted_version=student.consent_version,
        accepted_at=student.consent_at,
        needs_reconfirm=False,
    )
