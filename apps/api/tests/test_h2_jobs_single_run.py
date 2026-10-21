"""H-15 / AUD-HI-15: a scheduled job runs once across replicas -- proven with
real processes, not threads.

The claim mechanism is a durable database row (``job_runs`` with a composite
primary key) inserted by ``jobs.claim_period``: the winner's INSERT commits,
every loser's INSERT hits ``IntegrityError`` and the job skips. The audit's
note said "verified at database level; a literal two-process test was not run".
This file runs three separate interpreter processes that all race the same
schedule slot on the same SQLite file, released simultaneously by a shared
wall-clock start, and asserts exactly one reported ``ran=True``.

SQLite is the harsher test here: the losers must survive the write-lock race
(``busy_timeout=5000`` from ``db/session.py``) and still be rejected by the
primary key. On PostgreSQL the same INSERT has the same composite-PK shape.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import init_db, make_engine

API_ROOT = Path(__file__).resolve().parents[1]
SRC = API_ROOT / "src"
SECRET = "test-secret-0123456789abcdef0123456789"
PERIOD = datetime(2026, 10, 19, 3, 0, 0)

#: Runs in a fresh interpreter: build the engine, then claim the slot at a
#: shared start instant so the processes genuinely collide. CWD is a temp
#: directory without a .env, so no developer config leaks into the child.
CHILD = """
import json, os, sys, time
from datetime import datetime
sys.path.insert(0, os.environ["BGPT_SRC"])
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.jobs import run_retention_job

settings = Settings(
    env="test",
    database_url=os.environ["BGPT_DB"],
    jwt_secret=os.environ["BGPT_SECRET"],
    chat_retention_days=30,
    _env_file=None,
)
engine = make_engine(settings)
factory = make_session_factory(engine)
start = float(os.environ["BGPT_START"])
while time.time() < start:
    time.sleep(0.001)
result = run_retention_job(factory, settings, now=datetime(2026, 10, 19, 3, 0, 0))
print("RESULT " + json.dumps({"ran": bool(result.get("ran")), "reason": result.get("reason")}))
"""


@pytest.mark.integration
def test_scheduled_job_runs_once_across_three_processes(tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    url = f"sqlite:///{db_path.as_posix()}"
    settings = Settings(env="test", database_url=url, jwt_secret=SECRET)
    init_db(make_engine(settings))

    env = {
        **os.environ,
        "BGPT_SRC": str(SRC),
        "BGPT_DB": url,
        "BGPT_SECRET": SECRET,
        "BGPT_START": str(time.time() + 1.5),  # everyone loads imports, then races
    }
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD],
            cwd=tmp_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    outcomes = []
    for proc in processes:
        stdout, stderr = proc.communicate(timeout=120)
        assert proc.returncode == 0, stderr[-2000:]
        line = next((ln for ln in stdout.splitlines() if ln.startswith("RESULT ")), None)
        assert line, stdout + stderr
        outcomes.append(json.loads(line.removeprefix("RESULT ")))

    ran = [item for item in outcomes if item["ran"]]
    skipped = [item for item in outcomes if not item["ran"]]
    assert len(ran) == 1, outcomes
    assert len(skipped) == 2, outcomes
    assert all(item["reason"] == "already_ran" for item in skipped), skipped

    # The ledger holds exactly one row for the period, and the loser never
    # overwrote the winner's outcome.
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT job, period_key, outcome FROM job_runs WHERE job='retention_sweep'"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1, rows
    assert rows[0][1] == "2026-10-19"
    assert rows[0][2] is not None  # finish_period stamped the run


@pytest.mark.integration
def test_claim_period_is_the_only_winner_marker(tmp_path) -> None:
    """A second claim for the same slot fails even in a fresh process."""
    db_path = tmp_path / "claim.db"
    url = f"sqlite:///{db_path.as_posix()}"
    settings = Settings(env="test", database_url=url, jwt_secret=SECRET)
    engine = make_engine(settings)
    init_db(engine)

    script = """
import os, sys
sys.path.insert(0, os.environ["BGPT_SRC"])
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.jobs import claim_period
settings = Settings(env="test", database_url=os.environ["BGPT_DB"], jwt_secret=os.environ["BGPT_SECRET"], _env_file=None)
factory = make_session_factory(make_engine(settings))
with factory() as db:
    print("CLAIM", claim_period(db, "parent_digest", "2026-W42"))
"""
    env = {**os.environ, "BGPT_SRC": str(SRC), "BGPT_DB": url, "BGPT_SECRET": SECRET}
    first = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    second = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert "CLAIM True" in first.stdout, first.stdout + first.stderr
    assert "CLAIM False" in second.stdout, second.stdout + second.stderr
