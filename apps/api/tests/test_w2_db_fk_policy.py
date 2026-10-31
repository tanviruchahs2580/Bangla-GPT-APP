"""F-014/DB-01: every foreign key declares an ON DELETE policy, and the
database enforces it.

The audit found 52 foreign keys and zero ON DELETE actions: the erasure
policy for DELETE /users/me lived only in application code, so a new child
table the erasure path missed would make the delete fail with an
IntegrityError on PostgreSQL, and nothing at the database level backed the
deletion promise. These tests pin three things:

* the models and the migration's policy map agree, and every FK has a
  policy (a new FK cannot ship policy-free);
* the schema the migrations actually build carries those policies on both
  engines, and the migration is reversible (up -> down -> up);
* DELETE /users/me leaves no row anywhere pointing at the erased account --
  checked by walking the ORM metadata, so a table added later is covered
  the moment it declares a foreign key (the seed coverage test fails
  loudly if a new dependent table is not exercised).

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import bangla_gpt_api.db.models  # noqa: F401  (registers every table)
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.base import Base
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
    Concept,
    ConceptMastery,
    ConceptPrerequisite,
    Conversation,
    DailyActivity,
    EmailVerification,
    Feedback,
    Notification,
    ParentInvite,
    PasswordReset,
    QuestionBankEntry,
    QuestionPaper,
    QuizAttempt,
    RevisionItem,
    SavedNote,
    School,
    SchoolInvite,
    ShortTest,
    Student,
    StudentAbility,
    StudentInvite,
    SupportPlan,
    TeacherDocument,
    User,
)
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from conftest import engine_url

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = API_ROOT / "alembic" / "versions" / "c4d8e0f2a6b9_fk_delete_policy.py"

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
NOW = datetime.now(UTC).replace(tzinfo=None)

ACTIONS = {"CASCADE", "SET NULL", "NO ACTION"}

#: policy map from the migration, loaded by path so the map used by a
#: deployed migration and the one asserted here cannot drift.
_spec = importlib.util.spec_from_file_location("fk_policy_migration", MIGRATION)
assert _spec is not None and _spec.loader is not None
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)
FK_POLICY = _migration.FK_POLICY

#: tables the erasure seed below writes a row into. A table that references
#: users/students/teachers/parents and is not listed here fails
#: test_erasure_seed_covers_every_dependent_table. The three profile rows
#: themselves are created by POST /auth/register, not by the seed block.
SEEDED_TABLES = frozenset(
    {
        "students",  # created by registration
        "teachers",  # created by registration
        "parents",  # created by registration (test_parent_delete... covers it)
        "parent_student_links",
        "quiz_attempts",
        "answer_log",
        "conversations",
        "chat_messages",
        "parent_invites",
        "feedback",
        "chapter_progress",
        "daily_activity",
        "revision_queue",
        "class_students",
        "student_invites",
        "support_plans",
        "concept_mastery",
        "student_abilities",
        "question_papers",
        "teacher_documents",
        "assignments",
        "assignment_recipients",
        "short_tests",
        "question_bank",
        "saved_notes",
        "notifications",
        "password_resets",
        "email_verifications",
        "audit_log",
        "chapter_contents",
        "school_invites",
        "class_teachers",
        "ai_jobs",
        "ai_usage",
    }
)


def _policy_from_models() -> dict[str, dict[tuple[str, ...], str | None]]:
    out: dict[str, dict[tuple[str, ...], str | None]] = {}
    for table in Base.metadata.sorted_tables:
        per_table: dict[tuple[str, ...], str | None] = {}
        for column in table.columns:
            for fk in column.foreign_keys:
                per_table[(column.name,)] = fk.ondelete
        if per_table:
            out[table.name] = per_table
    return out


def test_every_foreign_key_declares_an_explicit_policy() -> None:
    """No FK may rely on the engine default (the DB-01 defect)."""
    missing = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        for fk in column.foreign_keys
        if not fk.ondelete
    ]
    assert not missing, f"foreign keys without ON DELETE: {missing}"
    unknown = [
        f"{table.name}.{column.name}={fk.ondelete}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        for fk in column.foreign_keys
        if fk.ondelete not in ACTIONS
    ]
    assert not unknown, f"unsupported ON DELETE actions: {unknown}"


def test_models_and_migration_declare_the_same_policy() -> None:
    """The migration's map IS the model policy -- both directions."""
    models = _policy_from_models()
    assert set(models) == set(FK_POLICY), (
        "tables with foreign keys differ between models and the policy "
        f"migration: models-only {sorted(set(models) - set(FK_POLICY))}, "
        f"migration-only {sorted(set(FK_POLICY) - set(models))}"
    )
    for table in models:
        assert models[table] == FK_POLICY[table], (
            f"{table}: models={models[table]} migration={FK_POLICY[table]}"
        )


def test_policy_map_has_no_unexplained_no_action() -> None:
    """NO ACTION is reserved for the two tenancy roots (see the migration).

    Every other relationship must cascade or null out, because a row that
    blocks its parent's deletion is exactly the erasure failure the policy
    exists to prevent.
    """
    blocked = sorted(
        f"{table}.{cols[0]}"
        for table, policy in FK_POLICY.items()
        for cols, action in policy.items()
        if action == "NO ACTION"
    )
    assert blocked == ["classrooms.school_id", "users.school_id"]


def _alembic(*args: str, database_url: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _sqlite_policies(connection: sa.Connection) -> dict[str, dict[tuple[str, ...], str]]:
    out: dict[str, dict[tuple[str, ...], str]] = {}
    for table in FK_POLICY:
        rows = connection.exec_driver_sql(f'PRAGMA foreign_key_list("{table}")').fetchall()
        out[table] = {(str(row[3]),): str(row[6]) for row in rows}
    return out


@pytest.fixture
def migrated_sqlite(tmp_path):
    """A fresh SQLite file at head, built by the real migration chain."""
    db_path = tmp_path / "fkpolicy.db"
    url = f"sqlite:///{db_path.as_posix()}"
    upgrade = _alembic("upgrade", "head", database_url=url)
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr
    engine = sa.create_engine(url)
    yield url, engine
    engine.dispose()


def _model_index_names() -> set[str]:
    """Indexes the ORM declares (the schema the migrations must produce)."""
    return {
        str(index.name)
        for table in Base.metadata.sorted_tables
        for index in table.indexes
        if index.name is not None
    }


def test_migrated_schema_carries_every_policy(migrated_sqlite) -> None:
    _, engine = migrated_sqlite
    with engine.connect() as connection:
        actual = _sqlite_policies(connection)
        assert actual == FK_POLICY
        # The rebuild must not lose indexes: asserting the database's index
        # set against the ORM's is the drift-free form of the audit's "89
        # indexes" count, and it also catches a lost column-level index
        # (alembic batch mode drops those silently -- why this migration
        # rebuilds the tables itself).
        in_db = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
            ).fetchall()
        }
        assert in_db == _model_index_names()
        assert (
            connection.exec_driver_sql(
                "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE '_fk_policy_tmp_%'"
            ).scalar()
            == 0
        )


def test_policy_migration_is_reversible(migrated_sqlite) -> None:
    """up -> down must restore NO ACTION everywhere; up must re-apply."""
    url, engine = migrated_sqlite
    down = _alembic("downgrade", "b5d7e9f1a3c7", database_url=url)
    assert down.returncode == 0, down.stdout + down.stderr
    with engine.connect() as connection:
        flat = {
            action for policy in _sqlite_policies(connection).values() for action in policy.values()
        }
    assert flat == {"NO ACTION"}, flat

    up = _alembic("upgrade", "head", database_url=url)
    assert up.returncode == 0, up.stdout + up.stderr
    check = _alembic("check", database_url=url)
    assert check.returncode == 0, check.stdout + check.stderr
    with engine.connect() as connection:
        assert _sqlite_policies(connection) == FK_POLICY


def test_cascades_and_nulling_are_enforced_by_the_database(migrated_sqlite) -> None:
    """Delete a parent row directly and watch the policy act.

    This is the point of the finding: the guarantee must not depend on the
    application having cleaned up first.
    """
    _, engine = migrated_sqlite
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        student_user = connection.exec_driver_sql(
            "INSERT INTO users (email, password_hash, role, created_at,"
            " must_change_password, email_verified, failed_login_count)"
            " VALUES ('cascade@example.com','x','student',CURRENT_TIMESTAMP,0,1,0)"
        ).lastrowid
        student = connection.exec_driver_sql(
            "INSERT INTO students (user_id, name, class_level, memory_enabled, created_at)"
            f" VALUES ({student_user}, 'Cascade', 6, 1, CURRENT_TIMESTAMP)"
        ).lastrowid
        attempt = connection.exec_driver_sql(
            "INSERT INTO quiz_attempts (student_id, class_level, status, quiz_json, created_at)"
            f" VALUES ({student}, 6, 'open', '[]', CURRENT_TIMESTAMP)"
        ).lastrowid
        connection.exec_driver_sql(
            "INSERT INTO answer_log (attempt_id, seq, question_text, chosen, correct_index,"
            " is_correct, chapter, book, created_at)"
            f" VALUES ({attempt}, 0, 'q?', 0, 1, 0, 'ch', 'book', CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO feedback (user_id, attempt_id, rating, triaged, created_at)"
            f" VALUES ({student_user}, {attempt}, 1, 0, CURRENT_TIMESTAMP)"
        )

        # the user row alone owns the whole chain
        connection.exec_driver_sql(f"DELETE FROM users WHERE id = {student_user}")
        for table in ("students", "quiz_attempts", "answer_log"):
            left = connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar()
            assert left == 0, f"{table} survived the cascade"
        pointer = connection.exec_driver_sql("SELECT attempt_id FROM feedback").scalar()
        assert pointer is None, "feedback must keep its row and drop the deleted pointer"


# --- the erasure guarantee -------------------------------------------------


@pytest.fixture
def pair(tmp_path):
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2fk"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    factory = make_session_factory(make_engine(settings))
    return client, factory


def _register(client: TestClient, email: str, role: str) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Tester", "role": role}
    if role == "student":
        payload.update(guardian_consent=True, class_level=6)
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _dependent_tables() -> set[str]:
    """Tables with a foreign key into the four account-owned roots."""
    roots = {"users.id", "students.id", "teachers.id", "parents.id"}
    return {
        table.name
        for table in Base.metadata.sorted_tables
        for column in table.columns
        for fk in column.foreign_keys
        if fk.target_fullname in roots
    }


def test_erasure_seed_covers_every_dependent_table() -> None:
    """A new FK into an account root must be exercised by the erasure test."""
    assert _dependent_tables() <= SEEDED_TABLES, (
        "tables referencing an account root but not seeded by the erasure "
        f"test: {sorted(_dependent_tables() - SEEDED_TABLES)}"
    )


def test_delete_me_leaves_no_row_pointing_at_the_erased_account(pair) -> None:
    """Walk every FK and assert nothing references the erased ids afterwards."""
    client, factory = pair
    prof = _register(client, "walk@example.com", "student")
    sid, uid = prof["profile_id"], prof["user_id"]
    teacher = _register(client, "walk-t@example.com", "teacher")

    with factory() as session:
        school = School(name="Walk School", code="WALK-1")
        concept = Concept(name="walk", class_level=6, subject="math", chapter="walk")
        session.add_all([school, concept])
        session.flush()
        room = ClassRoom(school_id=school.id, class_level=6, section="GEN")
        prereq = Concept(name="walk-prereq", class_level=6, subject="math", chapter="walk")
        session.add_all([room, prereq])
        session.flush()
        session.add(ConceptPrerequisite(concept_id=concept.id, prereq_id=prereq.id))
        attempt = QuizAttempt(student_id=sid, class_level=6, status="open")
        session.add(attempt)
        session.flush()
        conversation = Conversation(student_id=sid, title="chat")
        session.add(conversation)
        session.flush()
        assignment = Assignment(
            teacher_id=teacher["user_id"],
            subject="math",
            chapter="walk",
            due_at=NOW + timedelta(days=1),
        )
        session.add(assignment)
        session.flush()
        session.add_all(
            [
                AnswerLog(
                    attempt_id=attempt.id,
                    seq=0,
                    question_text="q?",
                    chosen=0,
                    correct_index=1,
                    is_correct=False,
                    chapter="walk",
                    book="walk",
                ),
                ChatMessage(conversation_id=conversation.id, role="user", content="hi"),
                ParentInvite(
                    code_hash="a" * 64, student_id=sid, expires_at=NOW + timedelta(days=1)
                ),
                Feedback(user_id=uid, attempt_id=attempt.id, rating=1),
                ChapterProgress(student_id=sid, subject="math", chapter="walk", class_level=6),
                DailyActivity(student_id=sid, date="2026-10-20", questions=1),
                RevisionItem(student_id=sid, question="q?", due_date="2026-10-21"),
                ClassStudent(classroom_id=room.id, student_id=sid),
                StudentInvite(
                    code_hash="b" * 64,
                    email="walk@example.com",
                    classroom_id=room.id,
                    student_id=sid,
                    expires_at=NOW + timedelta(days=30),
                ),
                SupportPlan(student_id=sid, teacher_id=teacher["user_id"], class_level=6),
                ConceptMastery(student_id=sid, concept_id=concept.id, correct=1, total=2),
                StudentAbility(student_id=sid, concept="walk", class_level=6),
                QuestionPaper(
                    teacher_id=uid,
                    class_level=6,
                    subject="math",
                    exam_type="exam",
                    marks=10,
                    duration_min=30,
                ),
                TeacherDocument(
                    teacher_id=uid, kind="worksheet", class_level=6, subject="math", title="ws"
                ),
                AssignmentRecipient(
                    assignment_id=assignment.id, student_id=sid, attempt_id=attempt.id
                ),
                ShortTest(classroom_id=room.id, teacher_id=uid, subject="math", chapter="walk"),
                QuestionBankEntry(
                    teacher_id=uid,
                    dedupe_key="c" * 64,
                    question_text="q?",
                    subject="math",
                    chapter="walk",
                    class_level=6,
                ),
                SavedNote(user_id=uid, title="n", body="b", source="tutor"),
                Notification(user_id=uid, kind="test", code="notif_test"),
                PasswordReset(user_id=uid, token_hash="d" * 64, expires_at=NOW + timedelta(days=1)),
                EmailVerification(
                    user_id=uid, token_hash="e" * 64, expires_at=NOW + timedelta(days=1)
                ),
                AuditLog(actor_user_id=uid, actor_role="student", action="data_export"),
                ChapterContent(subject="math", class_level=6, chapter="walk", created_by=uid),
                SchoolInvite(code_hash="f" * 64, school_id=school.id, created_by=uid),
                ClassTeacher(classroom_id=room.id, teacher_id=teacher["profile_id"]),
                AiJob(user_id=uid, kind="worksheet"),
                AiUsage(user_id=uid, route="tutor.ask"),
                AnalyticsEventRow(user_id=uid, name="quiz_started", role="student"),
            ]
        )
        session.commit()

    # every seeded row exists (otherwise the assertions below prove nothing)
    with factory() as session:
        for model in (AnswerLog, ChatMessage, Feedback, AiJob, AiUsage, AnalyticsEventRow):
            assert session.execute(select(func.count()).select_from(model)).scalar_one() >= 1

    deleted = client.request(
        "DELETE",
        "/users/me",
        headers=_headers(client, "walk@example.com"),
        json={"password": PASSWORD},
    )
    assert deleted.status_code == 204, deleted.text

    erased_ids = {"users.id": {uid}, "students.id": {sid}}
    offenders: list[str] = []
    with factory() as session:
        for table in Base.metadata.sorted_tables:
            if table.name == "users":
                continue
            for column in table.columns:
                for fk in column.foreign_keys:
                    if fk.target_fullname not in erased_ids:
                        continue
                    stmt = (
                        select(func.count())
                        .select_from(table)
                        .where(column.in_(erased_ids[fk.target_fullname]))
                    )
                    count = int(session.execute(stmt).scalar_one())
                    if count:
                        offenders.append(f"{table.name}.{column.name}={count}")
        # analytics_events deliberately has no FK (append-only trail) and is
        # anonymised instead of deleted -- it must not keep the pointer either.
        stale = int(
            session.execute(
                select(func.count())
                .select_from(AnalyticsEventRow)
                .where(AnalyticsEventRow.user_id == uid)
            ).scalar_one()
        )
    assert stale == 0, "analytics_events kept the erased user_id"
    assert not offenders, f"rows still referencing the erased account: {offenders}"

    with factory() as session:
        assert (
            session.execute(
                select(func.count()).select_from(User).where(User.id == uid)
            ).scalar_one()
            == 0
        )
        assert (
            session.execute(
                select(func.count()).select_from(Student).where(Student.id == sid)
            ).scalar_one()
            == 0
        )
        # documented survivors: shared content and the audit trail stay, authorless
        assert session.execute(select(func.count()).select_from(ChapterContent)).scalar_one() == 1
        audit = session.execute(
            select(AuditLog).where(AuditLog.action == "data_export")
        ).scalar_one()
        assert audit.actor_user_id is None


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("BGPT_TEST_DATABASE_URL", "").strip(),
    reason="needs BGPT_TEST_DATABASE_URL pointing at a throwaway PostgreSQL",
)
def test_policy_cycle_on_postgres() -> None:
    """The same up -> down -> up cycle against the production engine.

    Run with a throwaway container (see the stream report):
      docker run -d --name bgpt-w2-pg -e POSTGRES_PASSWORD=postgres \
        -e POSTGRES_DB=bgpt_w2 -p 55434:5432 postgres:16-alpine
      BGPT_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55434/bgpt_w2 \
        python -m pytest tests/test_w2_db_fk_policy.py -q
    """
    url = os.environ["BGPT_TEST_DATABASE_URL"]
    engine = sa.create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
        up = _alembic("upgrade", "head", database_url=url)
        assert up.returncode == 0, up.stdout + up.stderr

        def non_default_policies() -> int:
            with engine.connect() as connection:
                return int(
                    connection.execute(
                        sa.text(
                            "SELECT COUNT(*) FROM pg_constraint WHERE contype='f' AND confdeltype <> 'a'"
                        )
                    ).scalar_one()
                )

        assert non_default_policies() == 50  # 52 FKs, the two roots are NO ACTION
        down = _alembic("downgrade", "b5d7e9f1a3c7", database_url=url)
        assert down.returncode == 0, down.stdout + down.stderr
        assert non_default_policies() == 0
        again = _alembic("upgrade", "head", database_url=url)
        assert again.returncode == 0, again.stdout + again.stderr
        check = _alembic("check", database_url=url)
        assert check.returncode == 0, check.stdout + check.stderr
    finally:
        engine.dispose()
