"""SQLAlchemy models: content (split out of db/models.py, C-03)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models.base import (  # noqa: F401
    _utcnow as _utcnow,
)
from bangla_gpt_api.db.types import UtcDateTime


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
