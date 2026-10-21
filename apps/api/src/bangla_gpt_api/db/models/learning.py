"""SQLAlchemy models: learning (split out of db/models.py, C-03)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models.base import (  # noqa: F401
    _utcnow as _utcnow,
)
from bangla_gpt_api.db.types import UtcDateTime

if TYPE_CHECKING:  # pragma: no cover - annotation only, avoids a runtime sibling import
    from bangla_gpt_api.db.models.people import Student


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

    student: Mapped[Student] = relationship()


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
