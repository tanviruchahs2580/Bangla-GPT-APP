"""F-015 / DB-07: the e2e seeder refuses to run outside a test/dev lane.

The seeder upserts five accounts including a platform admin with the shared
literal password ``E2ePass!2345``, against whatever ``DATABASE_URL`` the shell
exports. Run from a shell holding a production .env, it published a privileged
account with a known password on the live system. The guard uses the app-side
``NON_PRODUCTION_ENVS`` convention (misspelled ENV values fail closed too).
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest

SEEDER_PATH = Path(__file__).resolve().parents[2] / "web" / "e2e" / "seed_e2e_users.py"


def _load_seeder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_e2e_users_under_test", SEEDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seeder_refuses_production_without_writing(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "prod.db"
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    seeder = _load_seeder()

    with pytest.raises(SystemExit) as excinfo:
        seeder.seed()

    assert "production" in str(excinfo.value)
    assert not db_path.exists(), "the guard must fire before the engine is built"


def test_seeder_refuses_a_misspelled_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ENV", "prodction")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'typo.db').as_posix()}")
    with pytest.raises(SystemExit):
        _load_seeder().seed()


def test_seeder_still_works_in_a_test_env(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "e2e.db"
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    seeder = _load_seeder()

    seeder.seed()

    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT email, role, email_verified FROM users ORDER BY email"
        ).fetchall()
    finally:
        conn.close()
    assert ("admin1@e2e.test", "admin", 1) in rows
    assert len(rows) == len(seeder.ACCOUNTS) + len(seeder.READONLY_ACCOUNTS)
