"""GDPR self-service export and erasure — extracted from routers/users.py.

The route layer carried a 481-line export and a 150-line erasure cascade
inline (audit M-07): untestable without HTTP, and the largest function in
the API. Both bodies moved here VERBATIM; the routes keep only route
policy (password re-auth F-142, last-admin guard, audit rows,
Content-Disposition) and delegate.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    AiJob,
    AiUsage,
    AnalyticsEventRow,
    AnswerLog,
    Assignment,
    AssignmentRecipient,
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
from bangla_gpt_api.schemas import DataExportResponse
from bangla_gpt_api.security import write_audit

#: export payload marker; consumers can branch on it (v2 adds the extended sections)
EXPORT_SCHEMA_VERSION = "2"


class _DataExportV2(DataExportResponse):
    """Export v2: the full per-user data set (S-021).

    The audit found the portability response omitted notes, notifications,
    chapter progress, revision items, the AI-usage ledger and analytics events
    -- all stored per user -- while ``DELETE /users/me`` cascaded through
    every one of them. A data subject received a partial answer to "what do
    you hold about me". F-040 added the graded-answer record (``answer_log``),
    the AI-memory preferences (``learning_prefs``/``memory_enabled``) and the
    per-attempt ``quiz_json``; v1's four sections and v2's table list are
    otherwise unchanged, so the version marker stays "2".

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
    # F-040: the child's graded-answer record. It is a child-scoped table the
    # erasure cascade deletes; the export skipped it, so a subject access
    # request answered without the question text and chosen answers.
    answer_log: list[dict] = Field(default_factory=list)
    # DB-01/F-040 follow-up: the relational bulk-assignment membership rows
    # (assignment_recipients) are as much the student's record as the JSON
    # list the export already carries, and they are what the erasure path
    # deletes row by row.
    assignment_memberships: list[dict] = Field(default_factory=list)
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


def _student_learning_sections(
    db: Session, student: Student | None, attempt_rows: list[QuizAttempt]
) -> dict[str, list[dict]]:
    """Every student-scoped learning table the export must carry (F-063/F-040).

    Returns the seven section lists keyed by the response field name; an unset
    student yields empty lists. Extracted from ``build_data_export`` so the
    builder reads one section per concept instead of forty branches, and so the
    completeness of this section can be reviewed and tested on its own.
    """
    sections: dict[str, list[dict]] = {
        "chapter_progress": [],
        "answer_log": [],
        "assignment_memberships": [],
        "revision_items": [],
        "concept_mastery": [],
        "student_abilities": [],
        "classrooms": [],
    }
    if student is None:
        return sections
    sections["chapter_progress"] = [
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
    sections["revision_items"] = [
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
    attempt_ids = [a.id for a in attempt_rows]
    sections["assignment_memberships"] = [
        {
            "assignment_id": row.assignment_id,
            "attempt_id": row.attempt_id,
            "created_at": _iso(row.created_at),
        }
        for row in db.execute(
            select(AssignmentRecipient)
            .where(AssignmentRecipient.student_id == student.id)
            .order_by(AssignmentRecipient.id)
        ).scalars()
    ]
    if attempt_ids:
        sections["answer_log"] = [
            {
                "id": row.id,
                "attempt_id": row.attempt_id,
                "seq": row.seq,
                "question_text": row.question_text,
                "chosen": row.chosen,
                "correct_index": row.correct_index,
                "is_correct": row.is_correct,
                "chapter": row.chapter,
                "book": row.book,
                "created_at": _iso(row.created_at),
            }
            for row in db.execute(
                select(AnswerLog)
                .where(AnswerLog.attempt_id.in_(attempt_ids))
                .order_by(AnswerLog.id)
            ).scalars()
        ]
    sections["concept_mastery"] = [
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
    sections["student_abilities"] = [
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
    sections["classrooms"] = [
        {
            "classroom_id": room.id,
            "school_id": room.school_id,
            "class_level": room.class_level,
            "section": room.section,
            "as": "student",
        }
        for room in db.execute(
            select(ClassRoom)
            .join(ClassStudent, ClassStudent.classroom_id == ClassRoom.id)
            .where(ClassStudent.student_id == student.id)
            .order_by(ClassRoom.id)
        ).scalars()
    ]
    return sections


def _teacher_classroom_rows(db: Session, teacher: Teacher | None) -> list[dict]:
    """A teacher's classroom assignments (class_teachers), the staff mirror."""
    if teacher is None:
        return []
    return [
        {
            "classroom_id": room.id,
            "school_id": room.school_id,
            "class_level": room.class_level,
            "section": room.section,
            "subject": assignment.subject,
            "as": "teacher",
        }
        for room, assignment in db.execute(
            select(ClassRoom, ClassTeacher)
            .join(ClassTeacher, ClassTeacher.classroom_id == ClassRoom.id)
            .where(ClassTeacher.teacher_id == teacher.id)
            .order_by(ClassRoom.id)
        ).all()
    ]


def build_data_export(db: Session, user: User) -> _DataExportV2:
    """Everything stored about this account (self-service portability)."""
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
            # F-040: the AI-memory preferences the student sees and can clear
            # in the UI were never exported.
            "learning_prefs": student.learning_prefs,
            "memory_enabled": student.memory_enabled,
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
        profile = {
            "type": "teacher",
            "id": teacher.id,
            "name": teacher.name,
            # F-040 follow-up: the teacher's own workflow preferences are
            # stored about them and were the one profile field omitted.
            "prefs": teacher.prefs,
        }
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
            # F-040: the question set itself (stem, options, correct index)
            # lives here; the export showed only the resulting score.
            "quiz_json": a.quiz_json,
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

    learning = _student_learning_sections(db, student, attempt_rows)
    chapter_progress = learning["chapter_progress"]
    answer_log = learning["answer_log"]
    assignment_memberships = learning["assignment_memberships"]
    revision_items = learning["revision_items"]
    concept_mastery = learning["concept_mastery"]
    student_abilities = learning["student_abilities"]

    classrooms = _teacher_classroom_rows(db, teacher)

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
        assignment_memberships=assignment_memberships,
        answer_log=answer_log,
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


def _strip_student_from_attempts_json(db: Session, student_id: int) -> None:
    """DB-01: Assignment/ShortTest carry an untyped ``attempts`` JSON list of
    ``{student_id, attempt_id}`` entries alongside the relational recipients
    table. Erasure cleaned the relational rows but left the JSON blobs
    holding the erased child's references — the teacher hub rendered a
    departed student's participation straight out of the untyped payload
    long after every relational trace was gone (a data-held-about-a-person
    residue). Entries naming the erased student are pruned in place; every
    other student's history in the same list is untouched.
    """
    from bangla_gpt_api.db.models import Assignment as _Assignment
    from bangla_gpt_api.db.models import ShortTest as _ShortTest

    def _prune(rows: Sequence[Any]) -> None:
        # The payload entries are untyped JSON (Any by contract here), so the
        # attribute access goes through getattr -- mypy cannot follow the
        # two-model union, and the shape really is checked at runtime below.
        for row in rows:
            entries = getattr(row, "attempts", None) or []
            kept = [
                entry
                for entry in entries
                if not (
                    isinstance(entry, dict) and str(entry.get("student_id", "")) == str(student_id)
                )
            ]
            if len(kept) != len(entries):
                row.attempts = kept
                db.add(row)

    _prune(db.execute(select(_Assignment).where(_Assignment.attempts.isnot(None))).scalars().all())
    _prune(db.execute(select(_ShortTest).where(_ShortTest.attempts.isnot(None))).scalars().all())


def erase_account_everything(db: Session, user: User) -> None:
    """Cascade-erase every row owned by the account, then the account row.

    Deletes across every FK-child (Postgres enforces them; SQLite does
    not), anonymises append-only attribution, and deletes the user. The
    commit stays with the caller (route) so its audit row lands with it.
    """
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
        # Bulk-assignment membership (BUG-4 recurrence): assignment_recipients
        # holds student_id -> students and attempt_id -> quiz_attempts, and no
        # erasure path ever deleted it. Every student who had received a bulk
        # assignment therefore hit a foreign-key violation here — the whole
        # transaction rolled back and DELETE /users/me answered 500, so the
        # students most likely to need erasure (a teacher's whole roster) were
        # exactly the ones who could not have it. The row goes before the
        # attempts it points at, and before the student row.
        db.execute(delete(AssignmentRecipient).where(AssignmentRecipient.student_id == student.id))
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
        _strip_student_from_attempts_json(db, student.id)
        db.delete(student)

    # User-scoped rows (any role), removed before the users row itself.
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    db.execute(delete(EmailVerification).where(EmailVerification.user_id == user.id))
    db.execute(delete(Feedback).where(Feedback.user_id == user.id))
    db.execute(delete(QuestionPaper).where(QuestionPaper.teacher_id == user.id))
    db.execute(delete(ShortTest).where(ShortTest.teacher_id == user.id))
    # Every roster member's recipient row points at the assignment rule below,
    # so the teacher's assignments cannot go before these rows do — the same
    # FK that broke the student side, seen from the other end. The recipients
    # belong to this teacher's assignments, not to the students, and the
    # attempts they reference are untouched.
    db.execute(
        delete(AssignmentRecipient).where(
            AssignmentRecipient.assignment_id.in_(
                select(Assignment.id).where(Assignment.teacher_id == user.id)
            )
        )
    )
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
