"""F-175/DB-02: the migrated schema carries no redundant prefix index.

The audit found ``ix_ai_usage_user_id`` sitting under the composite
``ix_ai_usage_user_created`` it duplicates: a single-column index on a
composite's leading column can never be chosen over the composite, so it is
pure write amplification (ai_usage is one row per generation). Migration
a3c5e7f9b1d3 pruned eleven of these and skipped the two that arrived later;
these tests keep the pattern from returning. The rule is general on purpose:
a future index=True added beside a new composite fails here instead of
silently costing an extra b-tree write per insert.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

API_ROOT = Path(__file__).resolve().parents[1]
#: revision just before the F-175 prune, for the reversibility leg.
PARENT_REVISION = "d2f6a8c0b4e1"


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


def _index_columns(url: str) -> dict[tuple[str, str], tuple[str, ...]]:
    """(table, index name) -> column tuple, from the live schema."""
    engine = sa.create_engine(url)
    try:
        inspector = sa.inspect(engine)
        out: dict[tuple[str, str], tuple[str, ...]] = {}
        for table in inspector.get_table_names():
            for index in inspector.get_indexes(table):
                name = index.get("name")
                if not name or name.startswith("sqlite_autoindex_"):
                    continue
                columns = tuple(index.get("column_names") or ())
                if columns:
                    out[(table, name)] = columns
        return out
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def migrated_url(tmp_path_factory) -> str:
    db = tmp_path_factory.mktemp("w2b_indexes") / "indexes.db"
    url = f"sqlite:///{db.as_posix()}"
    upgrade = _alembic("upgrade", "head", database_url=url)
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr
    return url


def test_no_migrated_index_is_a_prefix_of_another(migrated_url: str) -> None:
    indexes = _index_columns(migrated_url)
    offenders: list[str] = []
    for (table, name), columns in sorted(indexes.items()):
        for (other_table, other), other_columns in sorted(indexes.items()):
            if table != other_table or name == other:
                continue
            if len(columns) < len(other_columns) and other_columns[: len(columns)] == columns:
                offenders.append(f"{table}.{name}{columns} is a prefix of {other}{other_columns}")
    assert not offenders, "redundant prefix indexes:\n" + "\n".join(offenders)


def test_composites_that_serve_the_pruned_indexes_exist(migrated_url: str) -> None:
    indexes = _index_columns(migrated_url)
    assert indexes[("ai_usage", "ix_ai_usage_user_created")] == ("user_id", "created_at")
    assert indexes[("ai_jobs", "uq_ai_jobs_idempotency")] == (
        "user_id",
        "kind",
        "idempotency_key",
    )
    assert ("ai_usage", "ix_ai_usage_user_id") not in indexes
    assert ("ai_jobs", "ix_ai_jobs_user_id") not in indexes


def test_the_prune_migration_is_reversible(tmp_path) -> None:
    db = tmp_path / "reversible.db"
    url = f"sqlite:///{db.as_posix()}"
    up = _alembic("upgrade", "head", database_url=url)
    assert up.returncode == 0, up.stdout + up.stderr

    down = _alembic("downgrade", PARENT_REVISION, database_url=url)
    assert down.returncode == 0, down.stdout + down.stderr
    restored = _index_columns(url)
    assert ("ai_usage", "ix_ai_usage_user_id") in restored
    assert ("ai_jobs", "ix_ai_jobs_user_id") in restored

    again = _alembic("upgrade", "head", database_url=url)
    assert again.returncode == 0, again.stdout + again.stderr
    pruned = _index_columns(url)
    assert ("ai_usage", "ix_ai_usage_user_id") not in pruned
    assert ("ai_jobs", "ix_ai_jobs_user_id") not in pruned
