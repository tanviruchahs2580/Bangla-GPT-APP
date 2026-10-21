"""H-04/H-14/H-11: the three new migrations are reversible on SQLite.

``test_migrations_match_models.py`` proves upgrade+drift-check; this file adds
the half CI never exercised locally: the *downgrade* of the new revisions and
a clean re-upgrade afterwards. The database is a throwaway file created by the
test itself (never ``downgrade`` data you did not create), and the cycle is
run entirely through the alembic CLI so it exercises the same path a deploy
takes.

The previous head (``b4c6d8e0f2a4``) is the target of the downgrade: bringing
the database back to that revision reverses exactly the three revisions this
round added (H-04 checks/indexes, H-14 timestamptz, H-11 email prefs/bounces)
without touching history that shipped earlier.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

API_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD = "b4c6d8e0f2a4"  # revision before this round's three migrations
NEW_TABLES = {"email_bounces"}
NEW_COLUMNS = {("parents", "digest_opt_out"), ("parents", "digest_language")}


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


def _column_names(url: str, table: str) -> set[str]:
    engine = create_engine(url)
    try:
        return {col["name"] for col in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


@pytest.mark.integration
def test_new_migrations_reverse_and_reapply_cleanly_on_sqlite(tmp_path) -> None:
    url = f"sqlite:///{(tmp_path / 'cycle.db').as_posix()}"

    up = _alembic("upgrade", "head", database_url=url)
    assert up.returncode == 0, up.stdout + up.stderr
    assert "email_bounces" in inspect(create_engine(url)).get_table_names()
    assert "digest_opt_out" in _column_names(url, "parents")

    check = _alembic("check", database_url=url)
    assert check.returncode == 0, check.stdout + check.stderr

    down = _alembic("downgrade", PREVIOUS_HEAD, database_url=url)
    assert down.returncode == 0, down.stdout + down.stderr
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert not (NEW_TABLES & tables), tables
    for table, column in NEW_COLUMNS:
        assert column not in _column_names(url, table), (table, column)
    # The pruned index came back on the way down (nothing was lost).
    indexes = {index["name"] for index in inspect(create_engine(url)).get_indexes("class_students")}
    assert "ix_class_students_student_id" in indexes

    up_again = _alembic("upgrade", "head", database_url=url)
    assert up_again.returncode == 0, up_again.stdout + up_again.stderr
    check_again = _alembic("check", database_url=url)
    assert check_again.returncode == 0, check_again.stdout + check_again.stderr
    engine = create_engine(url)
    try:
        indexes = {index["name"] for index in inspect(engine).get_indexes("class_students")}
    finally:
        engine.dispose()
    assert "ix_class_students_student_id" not in indexes
