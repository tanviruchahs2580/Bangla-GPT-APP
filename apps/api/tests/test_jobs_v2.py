"""S5.4 PASS-WHEN: every scheduled period runs its side effects at most once.

The double-run hazards this guards: N gunicorn workers each running the loop,
a web loop plus the ARQ cron at the same wall-clock moment, a process restart
after an already-fired period, and a retried queue delivery. All of them hit
the same job_runs composite-PK ledger, proven here with real sqlite.
"""

import importlib.util
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import bangla_gpt_api.jobs as jobs
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"

# A Sunday at/after 16:00 UTC -> digest_due() is true (see test_parent_digest).
SUNDAY_DUE = datetime(2026, 9, 6, 16, 30)
MONDAY_MORNING = datetime(2026, 9, 7, 10, 0)


def _settings(tmp_path: Path, **kw) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/jobs.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
        **kw,
    )


@pytest.fixture
def factory(tmp_path):
    settings = _settings(tmp_path)
    engine = make_engine(settings)
    init_db(engine)
    yield make_session_factory(engine), settings
    engine.dispose()


# ---------- the ledger itself ----------


def test_claim_period_owners_get_one_slot(factory) -> None:
    session_factory, _ = factory
    db = session_factory()
    try:
        assert jobs.claim_period(db, "parent_digest", "2026-W36") is True
        # a second process/worker asking for the SAME period loses
        assert jobs.claim_period(db, "parent_digest", "2026-W36") is False
        # the next ISO week is a fresh slot; other jobs are independent
        assert jobs.claim_period(db, "parent_digest", "2026-W37") is True
        assert jobs.claim_period(db, "nightly_rollup", "2026-09-06") is True
    finally:
        db.close()


def test_finish_period_stores_outcome(factory) -> None:
    from bangla_gpt_api.db.models import JobRun

    session_factory, _ = factory
    db = session_factory()
    try:
        assert jobs.claim_period(db, "parent_digest", "2026-W36")
        jobs.finish_period(db, "parent_digest", "2026-W36", "families=2 sent=2")
        row = db.get(JobRun, ("parent_digest", "2026-W36"))
        assert row is not None and row.outcome == "families=2 sent=2"
        assert row.finished_at is not None
    finally:
        db.close()


# ---------- whole-job double runs (the real guarantee) ----------


def _seed_family(conn: sqlite3.Connection, parent_id: int, now: datetime) -> None:
    ts = str(now)
    conn.execute(
        "INSERT INTO users (email, password_hash, role, created_at)"
        " VALUES ('kid@job.test', 'x', 'student', ?)",
        (ts,),
    )
    sid = conn.execute("SELECT id FROM users WHERE email='kid@job.test'").fetchone()[0]
    conn.execute(
        "INSERT INTO students (user_id, name, class_level, consent_version, consent_at, created_at)"
        " VALUES (?, 'Rahim', 6, 'T-1', ?, ?)",
        (sid, ts, ts),
    )
    student_id = conn.execute("SELECT id FROM students WHERE user_id=?", (sid,)).fetchone()[0]
    conn.execute(
        "INSERT INTO parent_student_links (parent_id, student_id, created_at) VALUES (?, ?, ?)",
        (parent_id, student_id, ts),
    )
    conn.execute(
        "INSERT INTO conversations (student_id, title, last_strategy, created_at)"
        " VALUES (?, 'Algebra help', NULL, ?)",
        (student_id, ts),
    )
    conn.commit()


def test_weekly_digest_double_run_sends_one_email(factory, tmp_path) -> None:
    session_factory, settings = factory
    # register a parent through the app (row in parents table), seed a child
    client = TestClient(create_app(settings))
    res = client.post(
        "/auth/register",
        json={"email": "par@job.test", "password": PASSWORD, "role": "parent", "name": "Ayesha"},
    )
    assert res.status_code == 201, res.text
    conn = sqlite3.connect(f"{tmp_path}/jobs.db")
    try:
        parent_id = int(
            conn.execute(
                "SELECT p.id FROM parents p JOIN users u ON p.user_id=u.id WHERE u.email=?",
                ("par@job.test",),
            ).fetchone()[0]
        )
        _seed_family(conn, parent_id, SUNDAY_DUE)
    finally:
        conn.close()

    sent: list[str] = []

    def fake_sender(_s: Settings, *, to: str, subject: str, body: str) -> bool:
        sent.append(to)
        return True

    # THREE schedulers try the same Sunday: two inline workers + an ARQ cron.
    r1 = jobs.run_weekly_digest(session_factory, settings, now=SUNDAY_DUE, sender=fake_sender)
    r2 = jobs.run_weekly_digest(session_factory, settings, now=SUNDAY_DUE, sender=fake_sender)
    r3 = jobs.run_weekly_digest(session_factory, settings, now=SUNDAY_DUE, sender=fake_sender)

    assert r1["ran"] is True and r1["families"] == 1 and r1["delivered"] == 1
    assert r2 == {"ran": False, "reason": "already_ran", "period": r1["period"]}
    assert r3["ran"] is False and r3["reason"] == "already_ran"
    assert sent == ["par@job.test"]  # exactly one email for the whole week

    # next ISO week fires again
    r4 = jobs.run_weekly_digest(
        session_factory,
        settings,
        now=datetime(2026, 9, 13, 16, 30),
        sender=fake_sender,
    )
    assert r4["ran"] is True
    assert len(sent) == 2


def test_weekly_digest_not_due_touches_no_ledger(factory) -> None:
    session_factory, settings = factory
    r = jobs.run_weekly_digest(session_factory, settings, now=MONDAY_MORNING)
    assert r == {"ran": False, "reason": "not_due"}
    db = session_factory()
    try:
        n = db.execute(text("SELECT COUNT(*) FROM job_runs WHERE job='parent_digest'")).scalar_one()
        assert n == 0  # off-slot calls never burn a slot
    finally:
        db.close()


def test_nightly_rollup_double_run_is_single_recompute(factory) -> None:
    session_factory, settings = factory
    now = datetime(2026, 9, 6, 21, 30)  # >= NIGHTLY_HOUR_UTC
    r1 = jobs.run_nightly_rollup(session_factory, settings, now=now)
    r2 = jobs.run_nightly_rollup(session_factory, settings, now=now)
    assert r1["ran"] is True and r1["period"] == "2026-09-06"
    assert r2 == {"ran": False, "reason": "already_ran", "period": "2026-09-06"}
    # the next day is a fresh slot
    r3 = jobs.run_nightly_rollup(session_factory, settings, now=datetime(2026, 9, 7, 21, 30))
    assert r3["ran"] is True and r3["period"] == "2026-09-07"


def test_nightly_rollup_before_night_is_not_due(factory) -> None:
    session_factory, settings = factory
    r = jobs.run_nightly_rollup(session_factory, settings, now=datetime(2026, 9, 6, 20, 59))
    assert r == {"ran": False, "reason": "not_due"}


# ---------- scheduler wiring ----------


def test_invalid_jobs_backend_rejected_at_boot(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="JOBS_BACKEND"):
        create_app(_settings(tmp_path, jobs_backend="celery"))


def _startup_task_names(tmp_path, jobs_backend: str) -> dict:
    settings = _settings(
        tmp_path,
        jobs_backend=jobs_backend,
        parent_digest_enabled=True,
        weakness_refresh_enabled=True,
        parent_digest_check_minutes=360,
        weakness_refresh_check_minutes=360,
    )
    with TestClient(create_app(settings)) as c:
        return {
            "digest": getattr(c.app.state, "digest_task", None),
            "weakness": getattr(c.app.state, "weakness_task", None),
        }


def test_inline_backend_starts_in_process_loops(tmp_path) -> None:
    tasks = _startup_task_names(tmp_path, "inline")
    assert tasks["digest"] is not None and tasks["weakness"] is not None


def test_arq_backend_silences_the_web_loops(tmp_path) -> None:
    tasks = _startup_task_names(tmp_path, "arq")
    assert tasks["digest"] is None and tasks["weakness"] is None


def test_worker_settings_shape(tmp_path, monkeypatch) -> None:
    pytest.importorskip("arq")
    monkeypatch.setenv("REDIS_URL", "redis://redis.example:6380/1")
    spec = importlib.util.spec_from_file_location(
        "bgpt_worker", Path(__file__).resolve().parents[1] / "worker.py"
    )
    assert spec is not None and spec.loader is not None
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)

    ws = worker.WorkerSettings
    assert ws.redis_settings.host == "redis.example"
    assert ws.redis_settings.port == 6380
    names = {f.__name__ for f in ws.functions}
    assert names == {"job_weekly_digest", "job_nightly_rollup", "job_retention_sweep"}
    assert len(ws.cron_jobs) == 3
    # arq names cron entries "cron:<function>"
    by_name = {c.name.removeprefix("cron:"): c for c in ws.cron_jobs}
    # schedule mirrors the services' rules: Sunday>=16 UTC (digest), daily
    # retention sweep (S5.8) ~02:30 Dhaka, rollup 21 UTC daily
    assert set(by_name) == {
        "job_weekly_digest",
        "job_retention_sweep",
        "job_nightly_rollup",
    }
    assert by_name["job_weekly_digest"].weekday == 6
    assert by_name["job_weekly_digest"].hour >= 16
    assert by_name["job_retention_sweep"].hour == 20
    assert by_name["job_nightly_rollup"].hour == 21
