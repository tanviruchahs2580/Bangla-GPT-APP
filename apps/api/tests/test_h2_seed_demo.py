"""H-10: the demo seeder is deterministic and refuses production.

``scripts/seed_demo.py`` is the only seeder in the repository (the audit found
none). These tests pin the two properties that make it safe to keep:

* deterministic -- two runs on two empty databases produce identical rows
  (same RNG seed, same fixed clock instant), and the names are Bangla;
* production-refusing -- an ENV that looks like production, or any ENV outside
  the explicit allow-list, exits 2 and writes nothing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = API_ROOT / "scripts"
SECRET = "test-secret-0123456789abcdef0123456789"


def _load_seed_demo():
    spec = importlib.util.spec_from_file_location("seed_demo_h2", SCRIPTS / "seed_demo.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(API_ROOT / "src")}
    env.pop("DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "seed_demo.py"), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _fingerprint(db_path: Path) -> dict:
    """Every table's rows, with the one deliberate non-determinism normalised.

    ``users.password_hash`` is an argon2 hash with a random per-hash salt -- it
    must differ between runs (a deterministic hash would be a security defect),
    so the column is replaced by its column name before comparison; the salt
    property itself is asserted in
    ``test_password_hashes_are_salted_but_verify_the_demo_password``.
    """
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        all_rows: dict[str, list] = {}
        for table in tables:
            rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            if table == "users":
                columns = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
                hash_index = columns.index("password_hash")
                rows = [
                    tuple(
                        "<argon2-salted>" if index == hash_index else value
                        for index, value in enumerate(row)
                    )
                    for row in rows
                ]
            all_rows[table] = rows
        return {
            "all_rows": all_rows,
            "table_count": len(tables),
            "students": conn.execute(
                "SELECT name, class_level FROM students ORDER BY id"
            ).fetchall(),
            "users": conn.execute("SELECT email, role FROM users ORDER BY id").fetchall(),
            "attempts": conn.execute(
                "SELECT student_id, subject, correct, total, score_pct FROM quiz_attempts"
                " ORDER BY id"
            ).fetchall(),
            "activity": conn.execute(
                "SELECT student_id, date, questions, quizzes, minutes FROM daily_activity"
                " ORDER BY id"
            ).fetchall(),
        }
    finally:
        conn.close()


def _in_process_seed(db: Path) -> dict:
    seed_demo = _load_seed_demo()
    args = seed_demo.argparse.Namespace(
        database_url=f"sqlite:///{db.as_posix()}",
        env="test",
        students=8,
        days=4,
        seed=20261019,
        at="2026-10-01T00:00:00+00:00",
        force=False,
        out=None,
    )
    return seed_demo.seed(args)


def test_seed_is_deterministic_across_two_databases(tmp_path) -> None:
    """In-process: the CLI path is exercised by the other tests in this file."""
    first_db = tmp_path / "first.db"
    second_db = tmp_path / "second.db"
    first = _in_process_seed(first_db)
    second = _in_process_seed(second_db)
    assert first["counts"] == second["counts"]
    assert first["counts"]["students"] == 8
    fingerprint_a = _fingerprint(first_db)
    fingerprint_b = _fingerprint(second_db)
    assert fingerprint_a == fingerprint_b
    # The comparison covers every seeded table (a new table with a wall-clock
    # default would otherwise slip through a four-table fingerprint).
    assert fingerprint_a["table_count"] >= 20, fingerprint_a["table_count"]


def test_password_hashes_are_salted_but_verify_the_demo_password(tmp_path) -> None:
    """The one divergence the fingerprint normalises is verified, not ignored."""
    first_db = tmp_path / "salt-a.db"
    second_db = tmp_path / "salt-b.db"
    _in_process_seed(first_db)
    _in_process_seed(second_db)
    seed_demo = _load_seed_demo()
    sys.path.insert(0, str(API_ROOT / "src"))
    from bangla_gpt_api.auth.security import verify_password

    def hashes(path: Path) -> list[str]:
        conn = sqlite3.connect(path)
        try:
            return [row[0] for row in conn.execute("SELECT password_hash FROM users ORDER BY id")]
        finally:
            conn.close()

    first_hashes, second_hashes = hashes(first_db), hashes(second_db)
    assert first_hashes and second_hashes
    # Random salt per hash: two runs must NOT be byte-identical here...
    assert first_hashes != second_hashes
    # ...but every stored hash still verifies the documented demo password.
    assert all(verify_password(seed_demo.DEMO_PASSWORD, digest) for digest in first_hashes)
    assert all(verify_password(seed_demo.DEMO_PASSWORD, digest) for digest in second_hashes)
    assert not any(verify_password("not-the-demo-password", digest) for digest in first_hashes)


def test_seed_uses_bangla_names_and_demo_domain(tmp_path) -> None:
    db = tmp_path / "names.db"
    _in_process_seed(db)
    conn = sqlite3.connect(db)
    try:
        names = [row[0] for row in conn.execute("SELECT name FROM students").fetchall()]
        emails = [
            row[0]
            for row in conn.execute(
                "SELECT u.email FROM users u JOIN students s ON s.user_id = u.id"
            ).fetchall()
        ]
    finally:
        conn.close()
    # "রহিম" is the first seeded given name; assert real Bangla codepoints, not
    # an ASCII transliteration.
    assert any("\u09b0\u09b9\u09bf\u09ae" in name for name in names), names
    assert all(name and not name.isascii() for name in names), names
    assert all(email.endswith("@demo.bangla-gpt.test") for email in emails), emails


def test_seed_cli_refuses_production_without_writing(tmp_path) -> None:
    db = tmp_path / "refused.db"
    result = _run_cli(
        tmp_path,
        "--database-url",
        f"sqlite:///{db.as_posix()}",
        "--env",
        "production",
    )
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert '"seeded": false' in result.stdout, result.stdout
    # Nothing was written: the refusal happens before any DDL.
    assert not db.exists() or db.stat().st_size == 0


def test_seed_refuses_when_env_looks_production_like(tmp_path, monkeypatch) -> None:
    """``Settings.is_production`` is the second gate (e.g. ENV=staging)."""
    seed_demo = _load_seed_demo()
    sys.path.insert(0, str(API_ROOT / "src"))
    from bangla_gpt_api.config import Settings

    settings = Settings(
        _env_file=None,
        env="production",
        database_url=f"sqlite:///{(tmp_path / 'prod.db').as_posix()}",
        jwt_secret=SECRET,
    )
    with pytest.raises(SystemExit) as exit_info:
        seed_demo._guard(settings)
    # The guard's message is the contract; the CLI turns it into exit code 2.
    assert "production" in str(exit_info.value), exit_info.value
    assert not (tmp_path / "prod.db").exists()


def test_seed_refuses_to_run_twice_without_force(tmp_path) -> None:
    db = tmp_path / "twice.db"
    url = f"sqlite:///{db.as_posix()}"
    first = _run_cli(
        tmp_path,
        "--database-url",
        url,
        "--env",
        "test",
        "--students",
        "4",
        "--out",
        str(tmp_path / "first.json"),
    )
    assert first.returncode == 0, first.stderr
    second = _run_cli(tmp_path, "--database-url", url, "--env", "test", "--students", "4")
    assert second.returncode == 2, second.stdout
    assert "already has school" in json.loads(second.stdout)["reason"], second.stdout
    # --force rebuilds without duplicating.
    forced = _run_cli(
        tmp_path, "--database-url", url, "--env", "test", "--students", "4", "--force"
    )
    assert forced.returncode == 0, forced.stdout + forced.stderr
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT count(*) FROM schools").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM students").fetchone()[0] == 4
    finally:
        conn.close()
