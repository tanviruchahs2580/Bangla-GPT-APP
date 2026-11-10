"""Gates for revision dbf1d2e3f4a5 (DB-FIX-001..005) on the migrated schema.

Each test asserts a fact about the schema the MIGRATION CHAIN produces, not
about the model files alone: the whole point of DB-FIX-001 is that a database
can hold a CHECK the ORM never declared, so a model-level assertion would pass
on exactly the broken database. The fixture builds the chain once per module
and the ORM is driven against that schema, so a model that cannot insert into
its own migrated table fails here too.

Coverage, finding by finding:

* DB-FIX-001 -- answer_log carries ``chosen BETWEEN -1 AND 7`` (and the legacy
  ``chosen >= 0`` is gone), the ORM can insert the -1 "I did not answer"
  sentinel, out-of-range values are rejected, and a downgrade must not put the
  legacy definition back.
* DB-FIX-002 -- ai_jobs carries ``ck_ai_jobs_attempts`` and a negative
  ``attempts`` insert is rejected (the constraint existed in no migration).
* DB-FIX-003 -- the four indexes exist with the columns their query needs.
* DB-FIX-004 -- ai_usage.estimated_cost_usd is NUMERIC(14, 10) in the database
  and Numeric(14, 10) in the ORM (lockstep).
* DB-FIX-005 -- a migration run leaves the SQLite file in WAL (the runtime
  contention posture) while never enabling FK enforcement: the FK-rebuild
  revision c4d8e0f2a6b9 must still run in both directions. Its UPGRADE leg is
  already exercised by every fresh-chain fixture in this suite; the DOWNGRADE
  leg -- which no other test covers -- is asserted here.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AiJob, AiUsage, AnswerLog, QuizAttempt, Student, User

API_ROOT = Path(__file__).resolve().parents[1]
FIX_REVISION = "dbf1d2e3f4a5"
PARENT_REVISION = "e4b8c0d2f6a8"
#: The revision whose SQLite table rebuild requires PRAGMA foreign_keys=OFF
#: (see its docstring and alembic/env.py).
FK_REBUILD_REVISION = "c4d8e0f2a6b9"
FK_REBUILD_PARENT = "b5d7e9f1a3c7"

LEGACY_CHOSEN = "chosen >= 0"
INTENDED_CHOSEN = "chosen BETWEEN -1 AND 7"
DECIMAL_COST_DDL = "estimated_cost_usd numeric(14, 10) not null"

_NEW_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("chat_messages", "ix_chat_messages_created_at", ("created_at",)),
    ("conversations", "ix_conversations_created_at", ("created_at",)),
    ("ai_jobs", "ix_ai_jobs_status_updated", ("status", "updated_at")),
    ("assignment_recipients", "ix_assignment_recipients_attempt_id", ("attempt_id",)),
)


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


@pytest.fixture(scope="module")
def migrated_url(tmp_path_factory) -> str:
    """One full chain run for this module; every schema assertion reads it."""
    db = tmp_path_factory.mktemp("db_fix_v2") / "migrated.db"
    url = f"sqlite:///{db.as_posix()}"
    upgrade = _alembic("upgrade", "head", database_url=url)
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr
    return url


def _sqlite_path(url: str) -> str:
    path = sa.engine.make_url(url).database
    assert path is not None
    return path


def _table_ddl(url: str, table: str) -> str:
    with sqlite3.connect(_sqlite_path(url)) as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
    assert row is not None, f"{table}: not in the migrated schema"
    return str(row[0])


def _index_columns(url: str, table: str, name: str) -> tuple[str, ...]:
    engine = sa.create_engine(url)
    try:
        for index in sa.inspect(engine).get_indexes(table):
            if index.get("name") == name:
                return tuple(index.get("column_names") or ())
        return ()
    finally:
        engine.dispose()


def _normalised(sql: str) -> str:
    return " ".join(sql.split()).casefold()


@contextlib.contextmanager
def _orm_session(url: str) -> Iterator[Session]:
    engine = sa.create_engine(url)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def test_the_chain_is_still_single_and_linear() -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [FIX_REVISION], "the new revision must be the only head"
    assert script.get_revision(FIX_REVISION).down_revision == PARENT_REVISION

    revisions = list(script.walk_revisions())
    for revision in revisions:
        assert revision.down_revision is None or isinstance(revision.down_revision, str), (
            f"{revision.revision}: the chain must stay linear (no merge points)"
        )
        # every revision keeps a working downgrade(), including this one
        assert callable(revision.module.downgrade), f"{revision.revision}: no downgrade()"

    on_disk = [
        p for p in (API_ROOT / "alembic" / "versions").glob("*.py") if p.name != "__init__.py"
    ]
    assert len(revisions) == len(on_disk), (
        "every revision file must be reachable from the head, and vice versa"
    )


def test_answer_log_chosen_bounds_are_the_api_contract(migrated_url: str) -> None:
    ddl = _normalised(_table_ddl(migrated_url, "answer_log"))
    assert _normalised(INTENDED_CHOSEN) in ddl
    assert _normalised(LEGACY_CHOSEN) not in ddl, (
        "chosen >= 0 rejects the API's -1 'I did not answer' sentinel "
        "(schemas.py RevisionReviewIn, ge=-1)"
    )


def test_the_chosen_sentinel_inserts_and_the_bounds_bite(migrated_url: str) -> None:
    with _orm_session(migrated_url) as db:
        student = Student(name="DB fix learner", class_level=6)
        db.add(student)
        db.flush()
        attempt = QuizAttempt(student_id=student.id, class_level=6)
        db.add(attempt)
        db.flush()

        def answer(chosen: int) -> None:
            db.add(
                AnswerLog(
                    attempt_id=attempt.id,
                    seq=chosen + 1,
                    question_text="q",
                    chosen=chosen,
                    correct_index=0,
                    is_correct=False,
                    chapter="c",
                    book="b",
                )
            )
            db.commit()

        answer(-1)  # the sentinel the legacy constraint rejected
        answer(7)
        for out_of_range in (-2, 8):
            with pytest.raises(sa.exc.IntegrityError):
                answer(out_of_range)
            db.rollback()


def test_ai_jobs_attempts_check_exists_and_bites(migrated_url: str) -> None:
    assert "ck_ai_jobs_attempts" in _table_ddl(migrated_url, "ai_jobs")
    with _orm_session(migrated_url) as db:
        user = User(email="db-fix-002@example.test", password_hash="x", role="teacher")
        db.add(user)
        db.flush()
        db.add(AiJob(user_id=user.id, kind="worksheet", attempts=-1))
        with pytest.raises(sa.exc.IntegrityError):
            db.commit()
        db.rollback()


def test_hot_path_indexes_exist(migrated_url: str) -> None:
    for table, name, columns in _NEW_INDEXES:
        assert _index_columns(migrated_url, table, name) == columns, f"{table}.{name}"


def test_money_column_is_an_exact_decimal_in_schema_and_model(migrated_url: str) -> None:
    ddl = _normalised(_table_ddl(migrated_url, "ai_usage"))
    assert DECIMAL_COST_DDL in ddl, "the budget ledger column must be an exact decimal, not FLOAT"
    column_type = AiUsage.__table__.c.estimated_cost_usd.type
    assert isinstance(column_type, sa.Numeric)
    assert (column_type.precision, column_type.scale) == (14, 10)


def test_a_migration_run_leaves_the_runtime_sqlite_posture(migrated_url: str) -> None:
    """DB-FIX-005: alembic must not run with journal_mode=delete.

    WAL is a persistent property of the file, so it survives the run that set
    it -- an observable consequence of alembic/env.py installing the same
    pragmas db/session.py does. Before that change the file was left in
    ``delete`` mode, the posture whose write lock made an upgrade against a
    live single-file deployment fail on the first collision.
    """
    with sqlite3.connect(_sqlite_path(migrated_url)) as conn:
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"


def test_downgrade_keeps_the_fixed_bounds_and_never_enables_foreign_keys(
    migrated_url: str, tmp_path
) -> None:
    """The reversal legs: no reintroduced bug, and the FK rebuild still runs.

    The database is a copy of the migrated one: the module fixture must not be
    mutated, or every test after this one would read a downgraded schema.
    """
    url = f"sqlite:///{(tmp_path / 'reversal.db').as_posix()}"
    with sqlite3.connect(_sqlite_path(migrated_url)) as src:
        with sqlite3.connect(str(tmp_path / "reversal.db")) as dst:
            src.backup(dst)

    down = _alembic("downgrade", PARENT_REVISION, database_url=url)
    assert down.returncode == 0, down.stdout + down.stderr

    # DB-FIX-001: the bounds survive the downgrade -- the pre-revision state is
    # the bug, and a downgrade must never reintroduce it.
    ddl = _normalised(_table_ddl(url, "answer_log"))
    assert _normalised(INTENDED_CHOSEN) in ddl
    assert _normalised(LEGACY_CHOSEN) not in ddl
    # DB-FIX-002/003/004: genuinely reversed.
    assert "ck_ai_jobs_attempts" not in _table_ddl(url, "ai_jobs")
    assert _index_columns(url, "ai_jobs", "ix_ai_jobs_status_updated") == ()
    assert "estimated_cost_usd float not null" in _normalised(_table_ddl(url, "ai_usage"))

    # DB-FIX-005: the FK-rebuild revision needs PRAGMA foreign_keys=OFF. Its
    # downgrade raises rather than proceeding under enforcement
    # (c4d8e0f2a6b9:244-250), so this fails the moment a migration run enables
    # the pragma. No other test covers this direction.
    below_fk = _alembic("downgrade", FK_REBUILD_PARENT, database_url=url)
    assert below_fk.returncode == 0, (
        f"downgrading through {FK_REBUILD_REVISION} must run with "
        "PRAGMA foreign_keys=OFF (its own guard raises otherwise):\n"
        + below_fk.stdout
        + below_fk.stderr
    )

    again = _alembic("upgrade", "head", database_url=url)
    assert again.returncode == 0, again.stdout + again.stderr
    assert _normalised(INTENDED_CHOSEN) in _normalised(_table_ddl(url, "answer_log"))
    assert "ck_ai_jobs_attempts" in _table_ddl(url, "ai_jobs")
    assert _index_columns(url, "ai_jobs", "ix_ai_jobs_status_updated") == (
        "status",
        "updated_at",
    )
    assert DECIMAL_COST_DDL in _normalised(_table_ddl(url, "ai_usage"))
