"""Users Routes — split from the main.py god-module (ARCH-001).

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via :mod:`.deps`, shared helpers via :mod:`.common`.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, func, select, update

from bangla_gpt_api.db.models import (
    AiJob,
    AiUsage,
    AnswerLog,
    Assignment,
    AuditLog,
    ChapterContent,
    ChapterProgress,
    ChatMessage,
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
from bangla_gpt_api.schemas import (
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
    _build_me_response,
    authorize_student_access,
)

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/users/me", response_model=MeResponse)
def read_me(app_ctx: Ctx, db: DbSession, user: CurrentUser) -> MeResponse:
    return _build_me_response(app_ctx, db, user)


@router.delete("/users/me", status_code=204)
def delete_me(db: DbSession, user: CurrentUser) -> Response:
    """GDPR-style self-service account deletion.

    Removes the account and every row owned by it: student/teacher/parent
    profile and ALL FK-children (Postgres enforces referential integrity --
    SQLite silently does not, so every child table must be cleaned here or
    the delete aborts mid-transaction on the production engine). The last
    remaining admin cannot delete their own account (409).
    """
    if user.role == "admin":
        admins = db.execute(
            select(func.count()).select_from(User).where(User.role == "admin")
        ).scalar_one()
        if admins <= 1:
            raise HTTPException(status_code=409, detail="Cannot delete the last admin")

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
            db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conv_ids)))
        db.execute(delete(Conversation).where(Conversation.student_id == student.id))
        db.execute(delete(QuizAttempt).where(QuizAttempt.student_id == student.id))
        db.execute(delete(ParentStudentLink).where(ParentStudentLink.student_id == student.id))
        db.execute(delete(ParentInvite).where(ParentInvite.student_id == student.id))
        # S1.2/S1.9/S1.10 + S2/S4 children added after the original flow:
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
    # Wave 1 FK-children: teacher_documents, saved_notes, notifications
    # and ai_jobs must go before the users row (same BUG-4 rule).
    # analytics_events is deliberately NOT cleaned: it carries no FK to
    # users and the append-only product trail survives erasure.
    db.execute(delete(TeacherDocument).where(TeacherDocument.teacher_id == user.id))
    db.execute(delete(SavedNote).where(SavedNote.user_id == user.id))
    db.execute(delete(Notification).where(Notification.user_id == user.id))
    db.execute(delete(AiJob).where(AiJob.user_id == user.id))
    # AI-002 ledger rows go with the account (same BUG-4 rule).
    db.execute(delete(AiUsage).where(AiUsage.user_id == user.id))
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


@router.get("/users/me/export", response_model=DataExportResponse)
def export_me(response: Response, db: DbSession, user: CurrentUser) -> DataExportResponse:
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
    # S5.6 audit event 2/5: data_export (self-service; only the fact is
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
    return DataExportResponse(
        user={
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        profile=profile,
        quiz_attempts=attempts,
        parent_links=links,
    )


@router.get("/students/{student_id}", response_model=StudentResponse)
def get_student(student_id: int, db: DbSession, user: CurrentUser) -> StudentResponse:
    student = authorize_student_access(db, student_id, user)
    return StudentResponse(id=student.id, name=student.name, class_level=student.class_level)


@router.get("/students/{student_id}/consent", response_model=ConsentStatusOut)
def get_consent_status(student_id: int, db: DbSession, user: CurrentUser) -> ConsentStatusOut:
    """S5.8: is the stored guardian consent current for this student?"""
    student = authorize_student_access(db, student_id, user)
    return ConsentStatusOut(
        student_id=student.id,
        current_version=CONSENT_VERSION,
        accepted_version=student.consent_version,
        accepted_at=student.consent_at,
        needs_reconfirm=student.consent_version != CONSENT_VERSION,
    )


@router.post("/students/{student_id}/consent/reconfirm", response_model=ConsentStatusOut)
def post_consent_reconfirm(
    student_id: int,
    payload: ConsentReconfirmIn,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ConsentStatusOut:
    """S5.8 re-confirm flow: student or linked guardian accepts the
    CURRENT consent text; evidence trail (at/ip/version) is refreshed."""
    if not payload.accepted:
        raise HTTPException(
            status_code=400,
            detail={"code": "consent_not_accepted", "message": "acceptance required"},
        )
    # F-AUTH-02: align implementation with policy "student or linked guardian"
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
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
        # Broader access intentionally kept for admin/teacher support (documented deviation)
        allowed = True
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed to access this student")
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
