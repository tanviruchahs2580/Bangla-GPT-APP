"""H-04: database-enforced value invariants, FK indexes, redundant-index prune

Revision ID: a3c5e7f9b1d3
Revises: b4c6d8e0f2a4
Create Date: 2026-10-19

Three findings from the schema review, in one reversible revision:

1. **CHECK constraints** for the invariants that lived only in Pydantic and
   the routes (41 tables, 0 CheckConstraint before this): class_level 1-12,
   ratings, score_pct/read_pct 0-100, non-negative counters and durations, the
   role/status vocabularies, triaged/triaged_at consistency and
   correct <= total. A script, a manual repair or a future migration can no
   longer write a row the API would then serve.
2. **Missing FK indexes** (6): columns an erasure path scans or that a
   composite primary key does not cover.
3. **Redundant indexes pruned** (11): each is either an exact duplicate of a
   unique constraint's index or a strict prefix of a composite index on the
   same table -- established from ``pg_index`` on a migrations-built
   Postgres 16 database, not by reading the ORM.

PostgreSQL takes plain ADD CONSTRAINT: a full-table validation scan under
ACCESS EXCLUSIVE, so it belongs in the deploy window (tables are small). A
pre-existing violating row fails the migration loudly instead of passing
silently; find it with e.g. ``SELECT id FROM quiz_attempts WHERE score_pct <
0 OR score_pct > 100``. SQLite cannot ALTER TABLE ADD CONSTRAINT, so the same
constraints are applied through alembic batch mode (a copy-and-move table
recreate per table). Every statement is reversible.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3c5e7f9b1d3"
down_revision: str | Sequence[str] | None = "b4c6d8e0f2a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (index name, table, column) pruned by the upgrade, recreated by the downgrade.
_PRUNED_INDEXES = (
    ("ix_chapter_contents_subject", "chapter_contents", "subject"),
    ("ix_chapter_progress_student_id", "chapter_progress", "student_id"),
    ("ix_class_students_classroom_id", "class_students", "classroom_id"),
    ("ix_class_students_student_id", "class_students", "student_id"),
    ("ix_class_teachers_classroom_id", "class_teachers", "classroom_id"),
    ("ix_classrooms_school_id", "classrooms", "school_id"),
    ("ix_concepts_name", "concepts", "name"),
    ("ix_daily_activity_student_id", "daily_activity", "student_id"),
    ("ix_parent_student_links_parent_id", "parent_student_links", "parent_id"),
    ("ix_revision_queue_student_id", "revision_queue", "student_id"),
    ("ix_schools_code", "schools", "code"),
)

#: (index name, table, column) added for FK columns the plan review found bare.
_ADDED_INDEXES = (
    ("ix_chapter_contents_created_by", "chapter_contents", "created_by"),
    ("ix_concept_mastery_concept_id", "concept_mastery", "concept_id"),
    ("ix_concept_prerequisites_prereq_id", "concept_prerequisites", "prereq_id"),
    ("ix_parent_invites_used_by_parent_id", "parent_invites", "used_by_parent_id"),
    ("ix_school_invites_created_by", "school_invites", "created_by"),
    ("ix_school_invites_used_by", "school_invites", "used_by"),
)

#: table -> ((constraint name, condition), ...); mirrors db/models.py exactly.
_CHECKS: dict[str, tuple[tuple[str, str], ...]] = {
    "ai_jobs": (
        (
            "ck_ai_jobs_status",
            "status IN ('queued', 'generating', 'validating', 'ready', 'failed')",
        ),
    ),
    "ai_usage": (
        ("ck_ai_usage_prompt_tokens", "prompt_tokens >= 0"),
        ("ck_ai_usage_completion_tokens", "completion_tokens >= 0"),
        ("ck_ai_usage_estimated_cost_usd", "estimated_cost_usd >= 0"),
    ),
    "answer_log": (
        ("ck_answer_log_chosen", "chosen >= 0"),
        ("ck_answer_log_seq", "seq >= 0"),
        ("ck_answer_log_correct_index", "correct_index >= 0"),
    ),
    "assignments": (("ck_assignments_num_questions", "num_questions > 0"),),
    "chapter_contents": (
        ("ck_chapter_contents_version", "version >= 1"),
        ("ck_chapter_contents_class_level", "class_level BETWEEN 1 AND 12"),
    ),
    "chapter_progress": (
        ("ck_chapter_progress_class_level", "class_level BETWEEN 1 AND 12"),
        ("ck_chapter_progress_read_pct", "read_pct BETWEEN 0 AND 100"),
    ),
    "chat_messages": (
        ("ck_chat_messages_role", "role IN ('user', 'assistant')"),
        ("ck_chat_messages_rating", "rating IS NULL OR rating IN (-1, 1)"),
    ),
    "concepts": (("ck_concepts_class_level", "class_level BETWEEN 1 AND 12"),),
    "daily_activity": (
        ("ck_daily_activity_quizzes", "quizzes >= 0"),
        ("ck_daily_activity_questions", "questions >= 0"),
        ("ck_daily_activity_minutes", "minutes >= 0"),
        ("ck_daily_activity_date_iso", "length(date) = 10"),
    ),
    "feedback": (
        ("ck_feedback_triaged_at", "triaged = false OR triaged_at IS NOT NULL"),
        ("ck_feedback_rating", "rating BETWEEN -1 AND 1"),
    ),
    "practice_items": (
        ("ck_practice_items_class_level", "class_level BETWEEN 1 AND 12"),
        ("ck_practice_items_elo", "elo > 0"),
        ("ck_practice_items_attempts", "attempts >= 0"),
        ("ck_practice_items_correct_le_attempts", "correct <= attempts"),
        ("ck_practice_items_correct", "correct >= 0"),
    ),
    "question_bank": (
        ("ck_question_bank_times_reused", "times_reused >= 0"),
        ("ck_question_bank_answer_index", "answer_index IS NULL OR answer_index >= 0"),
        ("ck_question_bank_class_level", "class_level BETWEEN 1 AND 12"),
    ),
    "question_papers": (
        ("ck_question_papers_duration_min", "duration_min > 0"),
        ("ck_question_papers_status", "status IN ('draft', 'final')"),
        ("ck_question_papers_marks", "marks > 0"),
        ("ck_question_papers_class_level", "class_level BETWEEN 1 AND 12"),
    ),
    "quiz_attempts": (
        (
            "ck_quiz_attempts_score_pct",
            "score_pct IS NULL OR (score_pct >= 0 AND score_pct <= 100)",
        ),
        ("ck_quiz_attempts_correct", "correct IS NULL OR correct >= 0"),
        ("ck_quiz_attempts_class_level", "class_level BETWEEN 1 AND 12"),
        (
            "ck_quiz_attempts_correct_le_total",
            "total IS NULL OR correct IS NULL OR correct <= total",
        ),
        ("ck_quiz_attempts_total", "total IS NULL OR total >= 0"),
    ),
    "revision_queue": (
        ("ck_revision_queue_ease_factor", "ease_factor > 0"),
        ("ck_revision_queue_reps", "reps >= 0"),
        ("ck_revision_queue_correct_index", "correct_index >= 0"),
        ("ck_revision_queue_due_date_iso", "length(due_date) = 10"),
        ("ck_revision_queue_interval_days", "interval_days >= 0"),
    ),
    "school_invites": (("ck_school_invites_role", "role IN ('teacher', 'school_admin')"),),
    "short_tests": (
        ("ck_short_tests_num_questions", "num_questions > 0"),
        ("ck_short_tests_duration_min", "duration_min > 0"),
    ),
    "student_abilities": (
        ("ck_student_abilities_class_level", "class_level BETWEEN 1 AND 12"),
        ("ck_student_abilities_ability", "ability > 0"),
        ("ck_student_abilities_attempts", "attempts >= 0"),
    ),
    "students": (
        ("ck_students_name_not_blank", "length(name) > 0"),
        ("ck_students_class_level", "class_level BETWEEN 1 AND 12"),
    ),
    "support_plans": (("ck_support_plans_class_level", "class_level BETWEEN 1 AND 12"),),
    "users": (
        ("ck_users_failed_login_count", "failed_login_count >= 0"),
        ("ck_users_role", "role IN ('student', 'teacher', 'parent', 'admin', 'school_admin')"),
    ),
}


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _add_check(table: str, name: str, condition: str) -> None:
    if _postgres():
        op.create_check_constraint(name, table, condition)
    else:
        # SQLite has no ALTER TABLE ADD CONSTRAINT: recreate via batch mode.
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(name, condition)


def _drop_check(table: str, name: str) -> None:
    if _postgres():
        op.drop_constraint(name, table, type_="check")
    else:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")


def upgrade() -> None:
    # Prune first: a later batch recreate reflects the table, so a pruned
    # index must already be gone or batch mode would carry it back in.
    for index_name, table, _column in _PRUNED_INDEXES:
        op.drop_index(index_name, table_name=table)
    for index_name, table, column in _ADDED_INDEXES:
        op.create_index(index_name, table, [column], unique=False)
    for table, items in _CHECKS.items():
        for name, condition in items:
            _add_check(table, name, condition)


def downgrade() -> None:
    # Reverse order: constraints go first, then the indexes, then the pruned
    # indexes return with their original names and columns.
    for table, items in _CHECKS.items():
        for name, _condition in items:
            _drop_check(table, name)
    for index_name, table, _column in _ADDED_INDEXES:
        op.drop_index(index_name, table_name=table)
    for index_name, table, column in _PRUNED_INDEXES:
        op.create_index(index_name, table, [column], unique=False)
