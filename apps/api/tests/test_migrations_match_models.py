"""Guard against ORM/migration drift in the ordinary test run (AUD-0035).

`alembic check` was never invoked anywhere until it was wired into the
postgres CI job (commit c56266f), which immediately proved the models and the
migrations had diverged: two single-use hash indexes were non-unique in the
database but unique in the ORM, one ORM index was missing entirely, and a
column comment was absent. That job only runs on GitHub, so a developer could
still merge drift locally and discover it in CI.

This test runs the same command against a throwaway SQLite database from
within pytest. SQLite does not compare column comments, so the comment drift
is still caught only by the Postgres CI job; the index drift, which is the
part that affects behaviour, is caught here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]


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


@pytest.mark.integration
def test_migrations_match_models(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"

    upgrade = _alembic("upgrade", "head", database_url=database_url)
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr

    check = _alembic("check", database_url=database_url)
    assert check.returncode == 0, (
        "alembic check found ORM/migration drift; add a migration that matches "
        "the models:\n" + check.stdout + check.stderr
    )
