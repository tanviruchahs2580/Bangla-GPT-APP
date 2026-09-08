from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
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


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(16))
    # S3.1: school tenancy for staff accounts. NULL keeps pre-school-layer
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Only the SHA-256 hash of the single-use token is persisted.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    class_level: Mapped[int] = mapped_column(Integer)
    # Guardian-consent evidence trail (child-safety compliance, D20).
    consent_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consent_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Parent(Base):
    __tablename__ = "parents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    # S5.6: guardian phone, encrypted at rest (Fernet) whenever PII_ENC_KEY is
    # configured; None when no phone was given. Never logged, never exported.
    phone_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ParentStudentLink(Base):
    __tablename__ = "parent_student_links"
    __table_args__ = (UniqueConstraint("parent_id", "student_id", name="uq_parent_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    subject: Mapped[str | None] = mapped_column(String(60), nullable=True)
    class_level: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="open")
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    quiz_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    student: Mapped["Student"] = relationship()


class AnswerLog(Base):
    __tablename__ = "answer_log"

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
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Conversation(Base):
    """A multi-turn tutoring chat owned by exactly one student."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # S1.5: last explanation strategy used in this conversation ('আমি বুঝিন' loop).
    last_strategy: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="conversation")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text)
    grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    refused_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sources_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # -1 | +1
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class ParentInvite(Base):
    """Single-use invite code a student generates so a parent can link."""

    __tablename__ = "parent_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Only the SHA-256 hash of the code is persisted (same scheme as resets).
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_by_parent_id: Mapped[int | None] = mapped_column(ForeignKey("parents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Feedback(Base):
    """Thumbs up/down product feedback on tutor answers (B12)."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id"), nullable=True, index=True
    )
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("quiz_attempts.id"), nullable=True, index=True
    )
    rating: Mapped[int] = mapped_column(Integer)  # -1 or +1
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # S5.10 triage queue: admins work the queue oldest-first and mark rows
    # handled; triage_note is staff-facing text, still never chat/message logs.
    triaged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    triage_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ChapterProgress(Base):
    """S1.2: Per-student chapter progress (read%, completed, bookmarked)."""

    __tablename__ = "chapter_progress"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "subject", "chapter", "class_level", name="uq_chapter_progress"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    subject: Mapped[str] = mapped_column(String(60))
    chapter: Mapped[str] = mapped_column(String(200))
    class_level: Mapped[int] = mapped_column(Integer)
    read_pct: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    bookmarked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class DailyActivity(Base):
    """S1.9: per-day study activity in Asia/Dhaka (streak + heatmap source).

    'minutes' is a coarse estimate: each tutoring question or graded quiz counts
    as one minute of study; no client-side timing is trusted.
    """

    __tablename__ = "daily_activity"
    __table_args__ = (
        UniqueConstraint("student_id", "date", name="uq_daily_activity_student_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # ISO date in Asia/Dhaka
    questions: Mapped[int] = mapped_column(Integer, default=0)
    quizzes: Mapped[int] = mapped_column(Integer, default=0)
    minutes: Mapped[int] = mapped_column(Integer, default=0)


class RevisionItem(Base):
    """S1.10: SM-2-lite spaced-revision queue seeded from quiz results."""

    __tablename__ = "revision_queue"
    __table_args__ = (
        UniqueConstraint("student_id", "question", name="uq_revision_queue_student_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class School(Base):
    """S2.1: institution tenancy root; classrooms, teachers and students hang off it.

    The 2.1 migration backfills a single default school so pre-school-layer
    accounts keep working; stage 3 introduces school_admin-managed schools.
    """

    __tablename__ = "schools"
    __table_args__ = (UniqueConstraint("code", name="uq_school_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ClassRoom(Base):
    """S2.1: a class (NCTB class_level + section) inside a school."""

    __tablename__ = "classrooms"
    __table_args__ = (
        UniqueConstraint(
            "school_id", "class_level", "section", name="uq_classroom_school_level_section"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    class_level: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(8), default="GEN", server_default="GEN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ClassStudent(Base):
    """S2.1: enrollment linking a student to exactly one classroom (v1 rule)."""

    __tablename__ = "class_students"
    __table_args__ = (
        UniqueConstraint("classroom_id", "student_id", name="uq_class_student"),
        UniqueConstraint("student_id", name="uq_class_student_single_class"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ClassTeacher(Base):
    """S2.1: teacher assignment to a classroom (optionally per subject)."""

    __tablename__ = "class_teachers"
    __table_args__ = (
        UniqueConstraint("classroom_id", "teacher_id", "subject", name="uq_class_teacher"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    subject: Mapped[str] = mapped_column(
        String(60), default="", server_default="", comment="'' means all subjects"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class StudentInvite(Base):
    """S2.2: claim code for a student account created by class CSV import.

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
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ChapterContent(Base):
    """S2.3: versioned generated chapter study material (append-only versions).

    ``payload`` holds the seven section keys produced by the content engine
    (summary, notes, key_points, examples, practice_qs, homework, exam_tips).
    Teacher edits append a NEW row with a higher version; the current version
    is the max version for (subject, class_level, chapter).
    """

    __tablename__ = "chapter_contents"
    __table_args__ = (
        UniqueConstraint(
            "subject",
            "class_level",
            "chapter",
            "version",
            name="uq_chapter_content_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(60), index=True)
    class_level: Mapped[int] = mapped_column(Integer)
    chapter: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(12), default="ai")  # ai | teacher
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class QuestionPaper(Base):
    """S2.4: teacher-in-the-loop exam paper draft/final lifecycle.

    A draft is produced by ONE AI call plus validation (NCTB alignment,
    duplicate, difficulty). A paper can only be finalized after EVERY
    question was explicitly reviewed by the teacher (HIL gate).
    """

    __tablename__ = "question_papers"

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
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ShortTest(Base):
    """S2.5: class+chapter ultra-fast test -- one rule-based question set
    generated once and assigned to an entire classroom at once.

    Per-student grading reuses the existing quiz_attempts rows referenced in
    ``attempts``; duration is soft-enforced client/teacher-side (documented
    limitation: submit stays allowed after expiry so no work is lost).
    """

    __tablename__ = "short_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(60))
    chapter: Mapped[str] = mapped_column(String(200))
    num_questions: Mapped[int] = mapped_column(Integer, default=5)
    duration_min: Mapped[int] = mapped_column(Integer, default=10)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[list] = mapped_column(JSON, default=list)  # [{student_id, attempt_id}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SupportPlan(Base):
    """S2.7: three-week support plan for an at-risk student.

    Rule-generated (services/atrisk) from the student's weakest concepts:
    week 1 concept re-read, week 2 practice, week 3 assessment.
    """

    __tablename__ = "support_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    class_level: Mapped[int] = mapped_column(Integer)
    focus_concepts: Mapped[list] = mapped_column(JSON, default=list)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Assignment(Base):
    """S2.8: bulk assignment -- one rule-based question set shared by an
    explicitly selected group of students, tracked against a due date.

    Each selected student gets their own quiz_attempts row carrying the same
    dumped question set, so grading/AnswerLog/analytics all reuse the existing
    quiz pipeline untouched (R10).
    """

    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(60))
    chapter: Mapped[str] = mapped_column(String(200))
    num_questions: Mapped[int] = mapped_column(Integer, default=5)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[list] = mapped_column(JSON, default=list)  # [{student_id, attempt_id}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class QuestionBankEntry(Base):
    """S2.9: question bank -- every teacher-reviewed question lands here.

    ``dedupe_key`` is a sha256 over the NFKC/casefold/whitespace-collapsed
    question text, so re-reviewing the same question (or an AI draft that
    re-derives it) collapses onto one row instead of duplicating content.
    ``times_reused`` counts how often generation reused the entry.
    """

    __tablename__ = "question_bank"

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SchoolInvite(Base):
    """S3.1: single-use staff invite code for a school.

    Only the SHA-256 of the (uppercased, stripped) code is stored; the
    plaintext is returned exactly once at creation. Redemption stamps
    used_by/used_at and can never happen twice.
    """

    __tablename__ = "school_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="teacher")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Concept(Base):
    """S4.4 KG v1: a curriculum concept node (chapter-derived or LLM-extracted)."""

    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    class_level: Mapped[int] = mapped_column(Integer, index=True)
    subject: Mapped[str] = mapped_column(String(60), index=True)
    chapter: Mapped[str] = mapped_column(String(200))
    #: "chapter" (deterministic root) or "llm" (extracted + corpus-verified)
    source: Mapped[str] = mapped_column(String(16), default="chapter")
    #: colloquial/alternate spellings, e.g. বীজগণিত for বীজগণিতীয় রাশি
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("name", "class_level", "subject", name="uq_concept_identity"),
    )


class ConceptPrerequisite(Base):
    """S4.4 KG v1: directed edge concept -> prereq (a weak concept's gap hunt)."""

    __tablename__ = "concept_prerequisites"

    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), primary_key=True)
    prereq_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), primary_key=True)


class ConceptMastery(Base):
    """S4.4 KG v1: per-student per-concept mastery counts (graded answers)."""

    __tablename__ = "concept_mastery"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), primary_key=True)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PracticeItem(Base):
    """S4.5: adaptive practice -- Elo rating per generated cloze item.

    Identified by the generator's stable content fingerprint (question id =
    sha256 over chunk id + blanked term), so difficulty ratings accumulate
    across regenerations and quizzes.
    """

    __tablename__ = "practice_items"

    fingerprint: Mapped[str] = mapped_column(String(16), primary_key=True)
    chapter: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(60), index=True)
    class_level: Mapped[int] = mapped_column(Integer, index=True)
    elo: Mapped[float] = mapped_column(Float, default=1200.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class StudentAbility(Base):
    """S4.5: per-concept Elo-style ability, updated with every graded answer.

    Keyed by canonical concept name (chapter root) so abilities join the
    knowledge graph without an FK join on every graded answer.
    """

    __tablename__ = "student_abilities"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), primary_key=True)
    concept: Mapped[str] = mapped_column(String(200), primary_key=True)
    class_level: Mapped[int] = mapped_column(Integer, index=True)
    ability: Mapped[float] = mapped_column(Float, default=1200.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class JobRun(Base):
    """S5.4: idempotency ledger for scheduled jobs.

    One row per (job, period_key) claimed, enforced by the composite primary
    key. Any number of web workers / ARQ workers can race the same schedule
    slot: exactly one INSERT wins, the rest skip. This is what makes jobs
    double-run safe across pods (replaces the old per-process in-memory
    "last run" state, which broke under gunicorn -w N).
    """

    __tablename__ = "job_runs"

    job: Mapped[str] = mapped_column(String(80), primary_key=True)
    period_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AuditLog(Base):
    """S5.6: append-only trail for the five privileged event types:
    role_change, data_export, purge, qp_finalize, impersonation.

    Privacy (R11): only ids and outcome metadata live in ``detail`` --
    never message content, never PII. Rows are never updated or deleted.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    actor_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(40), index=True)
    target: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
