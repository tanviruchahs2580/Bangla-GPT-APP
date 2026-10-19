"""H-04 / AUD-HI-20: the database now enforces the value invariants.

Before this round: 41 tables, zero ``CheckConstraint`` -- class_level 1-12,
ratings, 0-100 percentages and non-negative counters lived only in Pydantic
and route code, so a script, a repair or a future migration could write a row
the API would then serve. This file proves the constraints exist on a fresh
schema and actually reject the bad values, and pins the index plan (pruned
duplicates/prefixes are gone from the model; the added FK indexes are there).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import CheckConstraint, Index
from sqlalchemy.exc import IntegrityError

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db import models as m
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory

SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def db(tmp_path):
    settings = Settings(env="test", database_url=f"sqlite:///{tmp_path}/inv.db", jwt_secret=SECRET)
    engine = make_engine(settings)
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        yield session


def _expect_rejected(db, obj, label: str) -> None:
    db.add(obj)
    with pytest.raises(IntegrityError, match="ck_"):
        db.commit()
    db.rollback()


def _user(db, email: str = "inv@example.com") -> m.User:
    user = m.User(email=email, password_hash="x", role="student")
    db.add(user)
    db.flush()
    return user


def _student(db, level: int = 6) -> m.Student:
    user = _user(db, f"st-{level}-{id(db)}@example.com")
    student = m.Student(
        user_id=user.id, name="Rahim", class_level=level, consent_version="T-1", consent_at=None
    )
    db.add(student)
    db.flush()
    return student


# ── the invariants that used to live only in application code ─────────


def test_students_class_level_must_be_1_to_12(db) -> None:
    _expect_rejected(
        db,
        m.Student(user_id=None, name="A", class_level=0, consent_version=None, consent_at=None),
        "class_level 0",
    )
    _expect_rejected(
        db,
        m.Student(user_id=None, name="A", class_level=13, consent_version=None, consent_at=None),
        "class_level 13",
    )
    db.commit()
    _student(db, 12)
    db.commit()  # boundary value is legal


def test_users_role_must_be_known(db) -> None:
    _expect_rejected(
        db, m.User(email="role@example.com", password_hash="x", role="superadmin"), "role value"
    )
    db.commit()
    db.add(m.User(email="ok@example.com", password_hash="x", role="school_admin"))
    db.commit()


def test_quiz_attempt_score_and_counts(db) -> None:
    student = _student(db)
    db.commit()
    _expect_rejected(
        db,
        m.QuizAttempt(
            student_id=student.id, subject="math", class_level=6, status="graded", score_pct=101.0
        ),
        "score_pct 101",
    )
    _expect_rejected(
        db,
        m.QuizAttempt(
            student_id=student.id,
            subject="math",
            class_level=6,
            status="graded",
            total=4,
            correct=5,
            score_pct=50.0,
        ),
        "correct > total",
    )
    _expect_rejected(
        db,
        m.QuizAttempt(
            student_id=student.id, subject="math", class_level=6, status="open", total=-1
        ),
        "negative total",
    )
    db.add(
        m.QuizAttempt(
            student_id=student.id,
            subject="math",
            class_level=6,
            status="graded",
            total=4,
            correct=4,
            score_pct=100.0,
        )
    )
    db.commit()


def test_chapter_progress_pct_and_feedback_rating(db) -> None:
    student = _student(db)
    user = _student(db, 7).user_id  # a second real user for the feedback FK
    db.commit()
    _expect_rejected(
        db,
        m.ChapterProgress(
            student_id=student.id, subject="math", chapter="c", class_level=6, read_pct=101
        ),
        "read_pct 101",
    )
    _expect_rejected(db, m.Feedback(user_id=user, rating=2), "feedback rating 2")
    db.add(
        m.ChapterProgress(
            student_id=student.id, subject="math", chapter="c", class_level=6, read_pct=100
        )
    )
    db.add(m.Feedback(user_id=user, rating=-1))
    db.add(m.Feedback(user_id=user, rating=0))  # comment-only row is legal
    db.commit()


def test_chat_message_role_and_rating(db) -> None:
    student = _student(db)
    conv = m.Conversation(student_id=student.id)
    db.add(conv)
    db.flush()
    db.commit()
    _expect_rejected(
        db, m.ChatMessage(conversation_id=conv.id, role="system", content="x"), "role system"
    )
    _expect_rejected(
        db,
        m.ChatMessage(conversation_id=conv.id, role="user", content="x", rating=0),
        "rating 0 on a message",
    )
    db.add(m.ChatMessage(conversation_id=conv.id, role="assistant", content="ok", rating=1))
    db.commit()


def test_daily_activity_and_practice_counters(db) -> None:
    student = _student(db)
    db.commit()
    _expect_rejected(
        db,
        m.DailyActivity(student_id=student.id, date="2026-01-01", minutes=-1),
        "negative minutes",
    )
    _expect_rejected(
        db, m.DailyActivity(student_id=student.id, date="2026-1-1"), "short non-ISO date"
    )
    _expect_rejected(
        db, m.DailyActivity(student_id=student.id, date="2026-01-01T"), "over-long date"
    )
    _expect_rejected(
        db,
        m.PracticeItem(
            fingerprint="f" * 16, chapter="c", subject="math", class_level=6, attempts=1, correct=2
        ),
        "correct > attempts",
    )
    _expect_rejected(
        db,
        m.PracticeItem(fingerprint="g" * 16, chapter="c", subject="math", class_level=6, elo=0.0),
        "elo 0",
    )
    db.add(m.PracticeItem(fingerprint="h" * 16, chapter="c", subject="math", class_level=6))
    db.commit()


def test_question_paper_and_job_status_vocabularies(db) -> None:
    teacher = _user(db, "qp-teacher@example.com")
    school = m.School(name="Inv School", code="INV-1")
    db.add(school)
    db.flush()
    db.commit()
    _expect_rejected(
        db,
        m.QuestionPaper(
            teacher_id=teacher.id,
            class_level=6,
            subject="math",
            exam_type="final",
            marks=0,
            duration_min=60,
            status="draft",
        ),
        "marks 0",
    )
    _expect_rejected(
        db,
        m.QuestionPaper(
            teacher_id=teacher.id,
            class_level=6,
            subject="math",
            exam_type="final",
            marks=100,
            duration_min=60,
            status="published",
        ),
        "status published",
    )
    _expect_rejected(
        db, m.AiJob(user_id=teacher.id, kind="worksheet", status="bogus"), "job status bogus"
    )
    _expect_rejected(db, m.AiUsage(user_id=teacher.id, prompt_tokens=-1), "negative prompt tokens")
    _expect_rejected(
        db,
        m.SchoolInvite(
            code_hash="z" * 64, school_id=school.id, role="admin", created_by=teacher.id
        ),
        "invite role admin",
    )
    db.add(
        m.QuestionPaper(
            teacher_id=teacher.id,
            class_level=6,
            subject="math",
            exam_type="final",
            marks=100,
            duration_min=60,
            status="final",
        )
    )
    db.add(m.AiJob(user_id=teacher.id, kind="worksheet", status="queued"))
    db.add(
        m.SchoolInvite(
            code_hash="y" * 64, school_id=school.id, role="teacher", created_by=teacher.id
        )
    )
    db.commit()


def test_email_bounce_count_is_positive(db) -> None:
    _expect_rejected(
        db,
        m.EmailBounce(recipient_hash="q" * 64, bounce_count=0),
        "bounce_count 0",
    )
    db.add(m.EmailBounce(recipient_hash="r" * 64))
    db.commit()


def test_feedback_triaged_at_consistency(db) -> None:
    user = _user(db, "triaged@example.com")
    db.commit()
    _expect_rejected(
        db, m.Feedback(user_id=user.id, rating=1, triaged=True), "triaged without stamp"
    )
    db.add(m.Feedback(user_id=user.id, rating=1, triaged=True, triaged_at=datetime.now(UTC)))
    db.commit()


# ── the index plan (H-04) ─────────────────────────────────────────────


PRUNED = (
    "ix_chapter_contents_subject",
    "ix_chapter_progress_student_id",
    "ix_class_students_classroom_id",
    "ix_class_students_student_id",
    "ix_class_teachers_classroom_id",
    "ix_classrooms_school_id",
    "ix_concepts_name",
    "ix_daily_activity_student_id",
    "ix_parent_student_links_parent_id",
    "ix_revision_queue_student_id",
    "ix_schools_code",
)
ADDED = (
    "ix_chapter_contents_created_by",
    "ix_concept_mastery_concept_id",
    "ix_concept_prerequisites_prereq_id",
    "ix_parent_invites_used_by_parent_id",
    "ix_school_invites_created_by",
    "ix_school_invites_used_by",
)


def _index_names() -> set[str]:
    return {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if isinstance(index, Index)
    }


def test_pruned_indexes_are_gone_from_the_model() -> None:
    names = _index_names()
    for name in PRUNED:
        assert name not in names, f"{name} is back in the model; re-run the index review"


def test_added_fk_indexes_are_declared() -> None:
    names = _index_names()
    for name in ADDED:
        assert name in names, f"{name} missing from the model"


def test_no_non_unique_index_is_a_duplicate_or_prefix_of_a_unique_index() -> None:
    """The invariant the prune restored: no redundant index may reappear.

    A non-unique index whose leading columns exactly repeat another index (or
    a unique constraint's index) on the same table is pure write overhead.
    """
    problems: list[str] = []
    for table in Base.metadata.tables.values():
        groups: list[tuple[str, tuple[str, ...], bool]] = []
        for index in table.indexes:
            groups.append(
                (str(index.name), tuple(c.name for c in index.columns), bool(index.unique))
            )
        for constraint in table.constraints:
            if constraint.__class__.__name__ == "UniqueConstraint" and constraint.columns:
                groups.append(
                    (str(constraint.name), tuple(c.name for c in constraint.columns), True)
                )
        for name, columns, unique in groups:
            if unique:
                continue
            for other_name, other_columns, other_unique in groups:
                if name == other_name or not other_unique:
                    continue
                if len(columns) <= len(other_columns) and columns == other_columns[: len(columns)]:
                    problems.append(f"{table.name}: {name} is covered by {other_name}")
    assert problems == [], problems


def test_check_constraint_inventory_covers_the_named_invariants() -> None:
    names = {
        str(constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert len(names) >= 50
    for required in (
        "ck_users_role",
        "ck_students_class_level",
        "ck_quiz_attempts_score_pct",
        "ck_chapter_progress_read_pct",
        "ck_feedback_rating",
        "ck_chat_messages_role",
        "ck_ai_jobs_status",
        "ck_email_bounces_count",
    ):
        assert required in names
