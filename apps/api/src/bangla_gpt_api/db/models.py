from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import false as sa_false
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.types import UtcDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    #: H-04: value invariants that lived only in Pydantic/routes, now enforced
    #: by the database so a script, migration or repair cannot write a row the
    #: API would then serve.
    __table_args__ = (
        CheckConstraint(
            "role IN ('student', 'teacher', 'parent', 'admin', 'school_admin')",
            name="ck_users_role",
        ),
        CheckConstraint("failed_login_count >= 0", name="ck_users_failed_login_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(16))
    # school tenancy for staff accounts. NULL keeps pre-school-layer
    # accounts (and the shared default school) working unchanged.
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id"), nullable=True, index=True
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=sa_false()
    )
    # Email verification: only enforced when SMTP delivery is configured;
    # otherwise accounts are auto-verified at registration.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default=sa_true()
    )
    # AUTH-001: TOTP secret (base32). NULL = MFA disabled. The secret is only
    # stored after the user proves possession (verify step), never at enroll.
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # F-05 token epoch: set at password change/reset. Any access token whose
    # ``iat`` is <= this moment is refused by get_current_user, so existing
    # sessions cannot ride out a credential rotation.
    sessions_invalidated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # S-002: per-account failed-login lockout. ``failed_login_count`` counts
    # consecutive password failures (reset to 0 by a successful sign-in);
    # ``locked_until`` is naive UTC (the SQLite column has no tzinfo) and is
    # stamped once the counter crosses the threshold, doubling for every
    # further failure up to the cap.
    failed_login_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Only the SHA-256 hash of the single-use token is persisted.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_students_class_level"),
        CheckConstraint("length(name) > 0", name="ck_students_name_not_blank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    class_level: Mapped[int] = mapped_column(Integer)
    # per-student learning preferences and the memory opt-out flag.
    # Both are additive; existing rows keep working via the server defaults.
    # the JSON payload is a keyed dict (whitelisted keys:
    # explanation_style, subject_focus) -- annotation-only change of the
    # stale 'list' annotation; the column itself is untyped JSON, so NO
    # migration is needed.
    learning_prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default=sa_true()
    )
    # Guardian-consent evidence trail (child-safety compliance, D20).
    consent_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    consent_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    # free-form teacher UI/workflow preferences (dict, additive).
    prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class Parent(Base):
    __tablename__ = "parents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    # notified (Fernet) whenever PII_ENC_KEY is
    # configured; None when no phone was given. Never logged, never exported.
    phone_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: H-11: user-level email preference. The weekly digest is the only bulk
    #: email the product sends; a guardian can opt out per account
    #: (transactional mail -- resets, verification -- is unaffected) and picks
    #: the digest language (bn | en).
    digest_opt_out: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=sa_false()
    )
    digest_language: Mapped[str] = mapped_column(
        String(2), default="bn", nullable=False, server_default="bn"
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ParentStudentLink(Base):
    __tablename__ = "parent_student_links"
    #: parent_id index pruned: uq_parent_student leads with it (H-04).
    __table_args__ = (UniqueConstraint("parent_id", "student_id", name="uq_parent_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_quiz_attempts_class_level"),
        CheckConstraint(
            "score_pct IS NULL OR (score_pct >= 0 AND score_pct <= 100)",
            name="ck_quiz_attempts_score_pct",
        ),
        CheckConstraint("total IS NULL OR total >= 0", name="ck_quiz_attempts_total"),
        CheckConstraint("correct IS NULL OR correct >= 0", name="ck_quiz_attempts_correct"),
        CheckConstraint(
            "total IS NULL OR correct IS NULL OR correct <= total",
            name="ck_quiz_attempts_correct_le_total",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    subject: Mapped[str | None] = mapped_column(String(60), nullable=True)
    class_level: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="open")
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    quiz_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)

    student: Mapped["Student"] = relationship()


class AnswerLog(Base):
    __tablename__ = "answer_log"
    __table_args__ = (
        CheckConstraint("seq >= 0", name="ck_answer_log_seq"),
        CheckConstraint("chosen >= 0", name="ck_answer_log_chosen"),
        CheckConstraint("correct_index >= 0", name="ck_answer_log_correct_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("quiz_attempts.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    question_text: Mapped[str] = mapped_column(String(2000))
    chosen: Mapped[int] = mapped_column(Integer)
    correct_index: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    chapter: Mapped[str] = mapped_column(String(200))
    book: Mapped[str] = mapped_column(String(200))


class EmailVerification(Base):
    """Single-use email verification token (hash stored, like resets)."""

    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class Conversation(Base):
    """A multi-turn tutoring chat owned by exactly one student."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # last explanation strategy used in this conversation ('আমি বুঝিন' loop).
    last_strategy: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="conversation")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
        CheckConstraint("rating IS NULL OR rating IN (-1, 1)", name="ck_chat_messages_rating"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text)
    grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    refused_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sources_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # -1 | +1
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class ParentInvite(Base):
    """Single-use invite code a student generates so a parent can link."""

    __tablename__ = "parent_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Only the SHA-256 hash of the code is persisted (same scheme as resets).
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: FK index added by H-04 (parent erasure scans this column).
    used_by_parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("parents.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class Feedback(Base):
    """Thumbs up/down product feedback on tutor answers."""

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("rating BETWEEN -1 AND 1", name="ck_feedback_rating"),
        CheckConstraint("triaged = false OR triaged_at IS NOT NULL", name="ck_feedback_triaged_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id"), nullable=True, index=True
    )
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("quiz_attempts.id"), nullable=True, index=True
    )
    # -1 = down, +1 = up, 0 = no verdict (comment-only feedback; the schema
    # keeps 0 valid because `rating` is required). Aggregates count -1/+1 only.
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # triage queue: admins work the queue oldest-first and mark rows
    # handled; triage_note is staff-facing text, still never chat/message logs.
    triaged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    triaged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    triage_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ChapterProgress(Base):
    """Per-student chapter progress (read%, completed, bookmarked)."""

    __tablename__ = "chapter_progress"
    #: The unique constraint's index covers the student_id prefix, so the old
    #: single-column student_id index was pure write overhead (H-04 prune).
    __table_args__ = (
        UniqueConstraint(
            "student_id", "subject", "chapter", "class_level", name="uq_chapter_progress"
        ),
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_chapter_progress_class_level"),
        CheckConstraint("read_pct BETWEEN 0 AND 100", name="ck_chapter_progress_read_pct"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    subject: Mapped[str] = mapped_column(String(60))
    chapter: Mapped[str] = mapped_column(String(200))
    class_level: Mapped[int] = mapped_column(Integer)
    read_pct: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    bookmarked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, onupdate=_utcnow)


class DailyActivity(Base):
    """per-day study activity in Asia/Dhaka (streak + heatmap source).

    'minutes' is a coarse estimate: each tutoring question or graded quiz counts
    as one minute of study; no client-side timing is trusted.
    """

    __tablename__ = "daily_activity"
    #: student_id index pruned: uq_daily_activity_student_date leads with it.
    __table_args__ = (
        UniqueConstraint("student_id", "date", name="uq_daily_activity_student_date"),
        CheckConstraint("questions >= 0", name="ck_daily_activity_questions"),
        CheckConstraint("quizzes >= 0", name="ck_daily_activity_quizzes"),
        CheckConstraint("minutes >= 0", name="ck_daily_activity_minutes"),
        CheckConstraint("length(date) = 10", name="ck_daily_activity_date_iso"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    date: Mapped[str] = mapped_column(String(10), index=True)  # ISO date in Asia/Dhaka
    questions: Mapped[int] = mapped_column(Integer, default=0)
    quizzes: Mapped[int] = mapped_column(Integer, default=0)
    minutes: Mapped[int] = mapped_column(Integer, default=0)


class RevisionItem(Base):
    """SM-2-lite spaced-revision queue seeded from quiz results."""

    __tablename__ = "revision_queue"
    #: student_id index pruned: uq_revision_queue_student_question leads with it.
    __table_args__ = (
        UniqueConstraint("student_id", "question", name="uq_revision_queue_student_question"),
        CheckConstraint("reps >= 0", name="ck_revision_queue_reps"),
        CheckConstraint("interval_days >= 0", name="ck_revision_queue_interval_days"),
        CheckConstraint("ease_factor > 0", name="ck_revision_queue_ease_factor"),
        CheckConstraint("correct_index >= 0", name="ck_revision_queue_correct_index"),
        CheckConstraint("length(due_date) = 10", name="ck_revision_queue_due_date_iso"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    question: Mapped[str] = mapped_column(Text)
    options_json: Mapped[list] = mapped_column(JSON, default=list)
    correct_index: Mapped[int] = mapped_column(Integer, default=0)
    chapter: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str | None] = mapped_column(String(60), nullable=True)
    class_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reps: Mapped[int] = mapped_column(Integer, default=0)  # consecutive successful recalls
    interval_days: Mapped[int] = mapped_column(Integer, default=0)  # 0 => due today
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    due_date: Mapped[str] = mapped_column(String(10), index=True)  # ISO, Asia/Dhaka
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, onupdate=_utcnow)


class School(Base):
    """institution tenancy root; classrooms, teachers and students hang off it.

    The 2.1 migration backfills a single default school so pre-school-layer
    accounts keep working; stage 3 introduces school_admin-managed schools.
    """

    __tablename__ = "schools"
    __table_args__ = (UniqueConstraint("code", name="uq_school_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    #: uq_school_code already indexes this column; a second index was pure
    #: write overhead (H-04 prune).
    code: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ClassRoom(Base):
    """a class (NCTB class_level + section) inside a school."""

    __tablename__ = "classrooms"
    __table_args__ = (
        UniqueConstraint(
            "school_id", "class_level", "section", name="uq_classroom_school_level_section"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: school_id index pruned: uq_classroom_school_level_section leads with it.
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_level: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(8), default="GEN", server_default="GEN")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ClassStudent(Base):
    """enrollment linking a student to exactly one classroom (v1 rule)."""

    __tablename__ = "class_students"
    #: Both column-level indexes were redundant (H-04 prune): classroom_id is
    #: the prefix of uq_class_student, student_id is covered exactly by
    #: uq_class_student_single_class.
    __table_args__ = (
        UniqueConstraint("classroom_id", "student_id", name="uq_class_student"),
        UniqueConstraint("student_id", name="uq_class_student_single_class"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ClassTeacher(Base):
    """teacher assignment to a classroom (optionally per subject)."""

    __tablename__ = "class_teachers"
    __table_args__ = (
        UniqueConstraint("classroom_id", "teacher_id", "subject", name="uq_class_teacher"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: classroom_id index pruned: uq_class_teacher leads with it (H-04).
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    subject: Mapped[str] = mapped_column(
        String(60), default="", server_default="", comment="'' means all subjects"
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class StudentInvite(Base):
    """claim code for a student account created by class CSV import.

    The code doubles as the initial password: the created user has
    must_change_password=True, so signing in with the code forces setting a
    personal password. Only the SHA-256 hash of the code is stored (same
    scheme as parent invites / resets); the plaintext is returned once.
    """

    __tablename__ = "student_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ChapterContent(Base):
    """versioned generated chapter study material (append-only versions).

    ``payload`` holds the seven section keys produced by the content engine
    (summary, notes, key_points, examples, practice_qs, homework, exam_tips).
    Teacher edits append a NEW row with a higher version; the current version
    is the max version for (subject, class_level, chapter).
    """

    __tablename__ = "chapter_contents"
    #: subject index pruned: uq_chapter_content_version leads with it (H-04).
    __table_args__ = (
        UniqueConstraint(
            "subject",
            "class_level",
            "chapter",
            "version",
            name="uq_chapter_content_version",
        ),
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_chapter_contents_class_level"),
        CheckConstraint("version >= 1", name="ck_chapter_contents_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: H-04 prune: uq_chapter_content_version leads with subject, and
    #: ix_chapter_contents_chapter stays for chapter-only lookups.
    subject: Mapped[str] = mapped_column(String(60))
    class_level: Mapped[int] = mapped_column(Integer)
    chapter: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(12), default="ai")  # ai | teacher
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    #: FK index added by H-04 (the account-erasure path deletes/updates by it).
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class QuestionPaper(Base):
    """teacher-in-the-loop exam paper draft/final lifecycle.

    A draft is produced by ONE AI call plus validation (NCTB alignment,
    duplicate, difficulty). A paper can only be finalized after EVERY
    a queue the teacher reviews. A paper can only be finalized after EVERY
    question was explicitly reviewed by the teacher (HIL gate).
    """

    __tablename__ = "question_papers"
    __table_args__ = (
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_question_papers_class_level"),
        CheckConstraint("marks > 0", name="ck_question_papers_marks"),
        CheckConstraint("duration_min > 0", name="ck_question_papers_duration_min"),
        CheckConstraint("status IN ('draft', 'final')", name="ck_question_papers_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    class_level: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(String(60))
    exam_type: Mapped[str] = mapped_column(String(40))
    marks: Mapped[int] = mapped_column(Integer)
    duration_min: Mapped[int] = mapped_column(Integer)
    difficulty: Mapped[dict] = mapped_column(JSON, default=dict)
    chapters: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(8), default="draft", index=True)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ShortTest(Base):
    """class+chapter ultra-fast test -- one rule-based question set
    generated once and assigned to an entire classroom at once.

    Per-student grading reuses the existing quiz_attempts rows referenced in
    ``attempts``; duration is soft-enforced client/teacher-side (documented
    limitation: submit stays allowed after expiry so no work is lost).
    """

    __tablename__ = "short_tests"
    __table_args__ = (
        CheckConstraint("num_questions > 0", name="ck_short_tests_num_questions"),
        CheckConstraint("duration_min > 0", name="ck_short_tests_duration_min"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(60))
    chapter: Mapped[str] = mapped_column(String(200))
    num_questions: Mapped[int] = mapped_column(Integer, default=5)
    duration_min: Mapped[int] = mapped_column(Integer, default=10)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[list] = mapped_column(JSON, default=list)  # [{student_id, attempt_id}]
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class SupportPlan(Base):
    """three-week support plan for an at-risk student.

    Rule-generated (services/atrisk) from the student's weakest concepts:
    week 1 concept re-read, week 2 practice, week 3 assessment.
    """

    __tablename__ = "support_plans"
    __table_args__ = (
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_support_plans_class_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    class_level: Mapped[int] = mapped_column(Integer)
    focus_concepts: Mapped[list] = mapped_column(JSON, default=list)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class Assignment(Base):
    """bulk assignment -- one rule-based question set shared by an
    explicitly selected group of students, tracked against a due date.

    Each selected student gets their own quiz_attempts row carrying the same
    dumped question set, so grading/AnswerLog/analytics all reuse the existing
    quiz pipeline untouched.
    """

    __tablename__ = "assignments"
    __table_args__ = (CheckConstraint("num_questions > 0", name="ck_assignments_num_questions"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(60))
    chapter: Mapped[str] = mapped_column(String(200))
    num_questions: Mapped[int] = mapped_column(Integer, default=5)
    due_at: Mapped[datetime] = mapped_column(UtcDateTime)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[list] = mapped_column(JSON, default=list)  # [{student_id, attempt_id}]
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class QuestionBankEntry(Base):
    """question bank -- every teacher-reviewed question lands here.

    ``dedupe_key`` is a sha256 over the NFKC/casefold/whitespace-collapsed
    question text, so re-reviewing the same question (or an AI draft that
    re-derives it) collapses onto one row instead of duplicating content.
    ``times_reused`` counts how often generation reused the entry.
    """

    __tablename__ = "question_bank"
    __table_args__ = (
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_question_bank_class_level"),
        CheckConstraint(
            "answer_index IS NULL OR answer_index >= 0", name="ck_question_bank_answer_index"
        ),
        CheckConstraint("times_reused >= 0", name="ck_question_bank_times_reused"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    question_text: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)
    answer_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subject: Mapped[str] = mapped_column(String(60))
    chapter: Mapped[str] = mapped_column(String(200))
    class_level: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(30), default="qp_review")
    times_reused: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class SchoolInvite(Base):
    """single-use, time-limited staff invite code for a school.

    Only the SHA-256 of the (uppercased, stripped) code is stored; the
    plaintext is returned exactly once at creation. Redemption stamps
    used_by/used_at, so a code can never be redeemed twice, and
    ``expires_at`` bounds its usable lifetime. Rows whose ``expires_at`` is
    NULL (pre-expiry schema) fail closed and are rejected as expired.
    """

    __tablename__ = "school_invites"
    __table_args__ = (
        CheckConstraint("role IN ('teacher', 'school_admin')", name="ck_school_invites_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="teacher")
    #: FK indexes added by H-04: both are read by the invite audit path.
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Concept(Base):
    """KG v1: a curriculum concept node (chapter-derived or LLM-extracted)."""

    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: name index pruned: uq_concept_identity leads with name (H-04).
    name: Mapped[str] = mapped_column(String(200))
    class_level: Mapped[int] = mapped_column(Integer, index=True)
    subject: Mapped[str] = mapped_column(String(60), index=True)
    chapter: Mapped[str] = mapped_column(String(200))
    #: "chapter" (deterministic root) or "llm" (extracted + corpus-verified)
    source: Mapped[str] = mapped_column(String(16), default="chapter")
    #: colloquial/alternate spellings, e.g. বীজগণিত for বীজগণিতীয় রাশি
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("name", "class_level", "subject", name="uq_concept_identity"),
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_concepts_class_level"),
    )


class ConceptPrerequisite(Base):
    """KG v1: directed edge concept -> prereq (a weak concept's gap hunt)."""

    __tablename__ = "concept_prerequisites"

    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), primary_key=True)
    #: FK index added by H-04: the PK (concept_id, prereq_id) does not cover
    #: the second FK column, which concept deletion and gap-hunt reads use.
    prereq_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), primary_key=True, index=True)


class ConceptMastery(Base):
    """KG v1: per-student per-concept mastery counts (graded answers)."""

    __tablename__ = "concept_mastery"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), primary_key=True)
    #: FK index added by H-04: the PK (student_id, concept_id) does not cover
    #: concept_id alone (per-concept reads, concept deletion).
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), primary_key=True, index=True)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class PracticeItem(Base):
    """adaptive practice -- Elo rating per generated cloze item.

    Identified by the generator's stable content fingerprint (question id =
    sha256 over chunk id + blanked term), so difficulty ratings accumulate
    across regenerations and quizzes.
    """

    __tablename__ = "practice_items"
    __table_args__ = (
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_practice_items_class_level"),
        CheckConstraint("elo > 0", name="ck_practice_items_elo"),
        CheckConstraint("attempts >= 0", name="ck_practice_items_attempts"),
        CheckConstraint("correct >= 0", name="ck_practice_items_correct"),
        CheckConstraint("correct <= attempts", name="ck_practice_items_correct_le_attempts"),
    )

    fingerprint: Mapped[str] = mapped_column(String(16), primary_key=True)
    chapter: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(60), index=True)
    class_level: Mapped[int] = mapped_column(Integer, index=True)
    elo: Mapped[float] = mapped_column(Float, default=1200.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, onupdate=_utcnow)


class StudentAbility(Base):
    """per-concept Elo-style ability, updated with every graded answer.

    Keyed by canonical concept name (chapter root) so abilities join the
    knowledge graph without an FK join on every graded answer.
    """

    __tablename__ = "student_abilities"
    __table_args__ = (
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_student_abilities_class_level"),
        CheckConstraint("ability > 0", name="ck_student_abilities_ability"),
        CheckConstraint("attempts >= 0", name="ck_student_abilities_attempts"),
    )

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), primary_key=True)
    concept: Mapped[str] = mapped_column(String(200), primary_key=True)
    class_level: Mapped[int] = mapped_column(Integer, index=True)
    ability: Mapped[float] = mapped_column(Float, default=1200.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, onupdate=_utcnow)


class JobRun(Base):
    """idempotency ledger for scheduled jobs.

    One row per (job, period_key) claimed, enforced by the composite primary
    key. Any number of web workers / ARQ workers can race the same schedule
    slot: exactly one INSERT wins, the rest skip. This is what makes jobs
    double-run safe across pods (replaces the old per-process in-memory
    "last run" state, which broke under gunicorn -w N).
    """

    __tablename__ = "job_runs"

    job: Mapped[str] = mapped_column(String(80), primary_key=True)
    period_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AuditLog(Base):
    """append-only trail for the five privileged event types:
    role_change, data_export, purge, qp_finalize, impersonation.

    Privacy: only ids and outcome metadata live in ``detail`` --
    never message content, never PII. Rows are never updated or deleted,
    with ONE documented exception: account erasure (DELETE /users/me)
    anonymises ``actor_user_id`` to NULL so the event survives the account
    while the erased person is no longer attributable (the column is
    nullable by design for this case).
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    actor_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(40), index=True)
    target: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


# ── Backend wave 1 ---------------------------------------------------------
# Five additive tables: teacher documents, saved notes, user notifications,
# a privacy-safe analytics trail and async generation jobs. All user-FK
# children here are cleaned in DELETE /users/me (BUG-4 / FK-completeness).


class TeacherDocument(Base):
    """persisted artifacts from the generic teacher generators.

    ``kind`` is one of lesson_plan | worksheet | answer_key | homework |
    rubric; ``payload`` holds the validated generator output so the document
    stays readable/printable even if the provider changes later.
    """

    __tablename__ = "teacher_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    class_level: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(String(60))
    chapter: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, index=True)


class SavedNote(Base):
    """user notes clipped from the tutor, a chapter or elsewhere."""

    __tablename__ = "saved_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))  # tutor | chapter | other
    source_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class Notification(Base):
    """in-app notification feed entry.

    ``code`` is an i18n code resolved by the client (never final copy) and
    ``params`` carries only ids/counts/safe labels.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    code: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    link: Mapped[str | None] = mapped_column(String(200), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, index=True)


class AnalyticsEventRow(Base):
    """persisted product analytics events (sanitized scalars only).

    ``user_id`` deliberately has NO FK: the trail is append-only privacy
    history cleaned by the retention sweep, so it must never block (or be
    blocked by) account deletion. Only sanitized scalar props live in
    ``props`` -- PII-looking keys are dropped before the row is written.
    """

    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    props: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, index=True)


class AiJob(Base):
    """async generation job (§37) with a linear status lifecycle.

    queued -> generating -> validating -> ready | failed. The job row is the
    single source of truth; the inline runner opens its own session so the
    request session is never reused.
    """

    __tablename__ = "ai_jobs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'generating', 'validating', 'ready', 'failed')",
            name="ck_ai_jobs_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, onupdate=_utcnow)


class AiUsage(Base):
    """AI-002: per-request LLM usage ledger (cost control foundation).

    One row per generation that reached a provider (ask/chat/stream/document
    jobs). Token counts are planning estimates (see services/costs.py), never
    vendor-metered values — good enough for budgets and dashboards, honest
    about precision. Cleaned by DELETE /users/me (BUG-4 rule).
    """

    __tablename__ = "ai_usage"

    __table_args__ = (
        CheckConstraint("prompt_tokens >= 0", name="ck_ai_usage_prompt_tokens"),
        CheckConstraint("completion_tokens >= 0", name="ck_ai_usage_completion_tokens"),
        CheckConstraint("estimated_cost_usd >= 0", name="ck_ai_usage_estimated_cost_usd"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    route: Mapped[str] = mapped_column(String(40), default="tutor.ask")
    model: Mapped[str] = mapped_column(String(80), default="mock")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, index=True)


class EmailBounce(Base):
    """H-11: suppression ledger for undeliverable recipients.

    Only the SHA-256 of the lowercased address is stored -- the ledger can
    suppress a bounced guardian without keeping a second copy of PII, and a
    hash is enough to match the recipient of every later send. ``reason`` is
    the operator-readable summary of the DSN status/diagnostic (never a
    message body). A row is never deleted by the app: suppression is the
    product decision, and the retention sweep leaves it alone.
    """

    __tablename__ = "email_bounces"
    __table_args__ = (
        UniqueConstraint("recipient_hash", name="uq_email_bounces_recipient_hash"),
        CheckConstraint("bounce_count >= 1", name="ck_email_bounces_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bounce_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    first_bounced_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    last_bounced_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
