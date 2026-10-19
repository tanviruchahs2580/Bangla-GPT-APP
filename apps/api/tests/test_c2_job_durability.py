"""C-08: a killed worker's job resumes or fails VISIBLY (two-process proof).

AUD-CD-05: generation jobs were ``asyncio.create_task`` fire-and-forget. A
SIGKILLed worker (rolling deploy, OOM) left the row at ``status='generating'``
forever -- no claim, no retry, no dead-letter, nothing alerting.

These tests are the verify method the finding asks for. They prove the
durability layer against a real file database and, where it matters, a real
second OS process:

* two processes claiming the same row -- exactly one wins (the idempotency
  key);
* a worker killed mid-job leaves an expired lease, and a *second process*
  picks the job up and drives it to ``ready``;
* when the retries are spent, the same kill dead-letters the job instead --
  a terminal, user-visible failure;
* the retry backoff is real (gated), jittered and bounded, and the attempt
  counter survives in the visible ``error`` text;
* a job that was never dispatched at all is picked up rather than stranded.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api import ai_jobs
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiJob, User
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.main import create_app

APP = Path(__file__).resolve().parents[1]
PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)
WORKSHEET_BODY = {"class_level": 6, "subject": "science", "chapter": CHAPTER}

#: A second OS process that tries the same DB claim against the same file.
_CLAIM_IN_SUBPROCESS = """
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from bangla_gpt_api import ai_jobs, jobs

url, job_id = sys.argv[1], sys.argv[2]
db = sessionmaker(bind=create_engine(url))()
try:
    print("CLAIMED" if ai_jobs.claim_ai_job(db, job_id) else "LOST")
finally:
    db.close()
"""


def _settings(db_url: str) -> Settings:
    return Settings(env="test", database_url=db_url, jwt_secret=SECRET)


def _factory(db_url: str):
    settings = _settings(db_url)
    engine = make_engine(settings)
    init_db(engine)
    return make_session_factory(engine), engine


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _register(client: TestClient, email: str) -> dict:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teach", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    return _login(client, email)


def _wait(client: TestClient, headers: dict, job_id: str, targets: tuple[str, ...], timeout=20.0):
    deadline = time.monotonic() + timeout
    body = None
    while time.monotonic() < deadline:
        res = client.get(f"/teacher/jobs/{job_id}", headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        if body["status"] in targets:
            return body
        time.sleep(0.05)
    pytest.fail(f"job never reached {targets}: last={body}")


def _seed_teacher_and_job(
    db_url: str,
    *,
    kind: str = "worksheet",
    status: str = "queued",
    error: str | None = None,
    age_seconds: float = 0.0,
) -> str:
    """Insert a teacher + a job row directly, to control the starting state."""
    factory, engine = _factory(db_url)
    db = factory()
    try:
        user = User(
            email=f"seed-{int(time.time() * 1000)}@durable.test", password_hash="x", role="teacher"
        )
        db.add(user)
        db.flush()
        job = AiJob(
            user_id=user.id,
            kind=kind,
            payload=dict(WORKSHEET_BODY),
            status=status,
            error=error,
        )
        db.add(job)
        db.commit()
        if age_seconds:
            job.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=age_seconds)
            db.commit()
        return str(job.id)
    finally:
        db.close()
        engine.dispose()


# --------------------------------------------------- two processes claim --


def _claim_via_subprocess(db_url: str, job_id: str) -> str:
    env = {**os.environ, "PYTHONPATH": str(APP / "src")}
    proc = subprocess.run(
        [sys.executable, "-c", _CLAIM_IN_SUBPROCESS, db_url, job_id],
        cwd=APP,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return str(proc.stdout.strip().splitlines()[-1])


def test_another_os_process_cannot_claim_a_row_this_process_holds(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path}/claim.db"
    job_id = _seed_teacher_and_job(db_url)
    factory, engine = _factory(db_url)
    db = factory()
    try:
        assert ai_jobs.claim_ai_job(db, job_id) is True  # this process wins
    finally:
        db.close()

    assert _claim_via_subprocess(db_url, job_id) == "LOST"  # the other one loses
    db = factory()
    try:
        assert db.execute(select(AiJob.status).where(AiJob.id == job_id)).scalar_one() == (
            ai_jobs.AI_JOB_GENERATING
        )
    finally:
        db.close()
        engine.dispose()


def test_a_second_process_wins_when_this_process_has_not_claimed(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path}/claim2.db"
    job_id = _seed_teacher_and_job(db_url)
    assert _claim_via_subprocess(db_url, job_id) == "CLAIMED"

    factory, engine = _factory(db_url)
    db = factory()
    try:
        assert ai_jobs.claim_ai_job(db, job_id) is False
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------- killed worker: resume ------


def test_killed_worker_job_is_resumed_by_the_next_process(tmp_path) -> None:
    """The audit's verify method: kill the worker mid-job.

    The first app runs the job to completion; then we rewrite the row into
    exactly the shape a SIGKILL leaves behind (``generating``, expired lease,
    no result) and let a SECOND app process boot. Its startup sweep must
    recover the job and drive it back to ``ready``.
    """
    db_url = f"sqlite:///{tmp_path}/resume.db"
    settings = _settings(db_url)
    with TestClient(create_app(settings)) as first:
        headers = _register(first, "resume@durable.test")
        res = first.post(
            "/teacher/jobs", json={"kind": "worksheet", "payload": WORKSHEET_BODY}, headers=headers
        )
        assert res.status_code == 202, res.text
        job_id = res.json()["id"]
        _wait(first, headers, job_id, ("ready",))

    # --- simulate the hard kill: in-flight row, no heartbeat for an hour ----
    factory, engine = _factory(db_url)
    db = factory()
    try:
        row = db.get(AiJob, job_id)
        assert row is not None
        row.status = ai_jobs.AI_JOB_GENERATING
        row.result = None
        row.error = None
        row.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        db.commit()
    finally:
        db.close()
        engine.dispose()

    # --- the next process boots and must recover it --------------------------
    with TestClient(create_app(settings)) as second:
        headers = _login(second, "resume@durable.test")
        body = _wait(second, headers, job_id, ("ready",))
        assert body["result"] and body["result"]["document_id"]
        assert body["status"] == ai_jobs.AI_JOB_READY

    factory, engine = _factory(db_url)
    db = factory()
    try:
        row = db.get(AiJob, job_id)
        assert row is not None and row.status == ai_jobs.AI_JOB_READY
        assert row.error is None, "a job that ends ready must not keep a stale attempt marker"
        assert row.result and row.result["document_id"]
    finally:
        db.close()
        engine.dispose()


def test_killed_worker_with_spent_retries_fails_visibly(tmp_path) -> None:
    """Same kill, but the retry budget is gone: the job must FAIL, visibly.

    Nothing here may stay in flight: the row ends terminal, and the teacher's
    own ``GET /teacher/jobs/{id}`` returns the terminal state with the reason
    instead of an eternal "generating".
    """
    db_url = f"sqlite:///{tmp_path}/deadletter.db"
    settings = _settings(db_url)
    with TestClient(create_app(settings)) as first:
        headers = _register(first, "dl@durable.test")
        res = first.post(
            "/teacher/jobs", json={"kind": "worksheet", "payload": WORKSHEET_BODY}, headers=headers
        )
        assert res.status_code == 202, res.text
        job_id = res.json()["id"]
        _wait(first, headers, job_id, ("ready",))

    # kill-shaped rewrite: in-flight, two attempts already spent, stale lease
    factory, engine = _factory(db_url)
    db = factory()
    try:
        row = db.get(AiJob, job_id)
        assert row is not None
        row.status = ai_jobs.AI_JOB_GENERATING
        row.result = None
        row.error = ai_jobs._attempt_error(ai_jobs.AI_JOB_MAX_ATTEMPTS - 1, "ProviderError")
        row.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        db.commit()
    finally:
        db.close()
        engine.dispose()

    with TestClient(create_app(settings)) as second:
        headers = _login(second, "dl@durable.test")
        body = _wait(second, headers, job_id, ("ready", "failed"))
        assert body["status"] == ai_jobs.AI_JOB_FAILED, "a spent budget must not retry forever"
        assert "dead-lettered" in (body["error"] or "")
        assert "retries spent after lost leases" in (body["error"] or "")

    factory, engine = _factory(db_url)
    db = factory()
    try:
        row = db.get(AiJob, job_id)
        assert row is not None and row.status == ai_jobs.AI_JOB_FAILED
        assert ai_jobs.is_dead_lettered(row)
        assert body["error"] == row.error  # what the API showed is what is stored
    finally:
        db.close()
        engine.dispose()


def test_never_dispatched_queued_job_is_picked_up(tmp_path) -> None:
    """A process that died between the commit and create_task strands a row."""
    db_url = f"sqlite:///{tmp_path}/stranded.db"
    job_id = _seed_teacher_and_job(db_url, status=ai_jobs.AI_JOB_QUEUED, age_seconds=7 * 24 * 3600)
    factory, engine = _factory(db_url)
    try:
        assert ai_jobs.recover_stale_ai_jobs(factory) == [job_id]
    finally:
        engine.dispose()


# ------------------------------------------------ retry: backoff + jitter --


def test_transient_failure_schedules_a_retry_then_dead_letters(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path}/retry.db"
    job_id = _seed_teacher_and_job(db_url, status=ai_jobs.AI_JOB_QUEUED)
    factory, engine = _factory(db_url)
    db = factory()
    try:
        # Each attempt starts with the runner's claim (queued -> generating),
        # so the failure handler always sees an in-flight row.
        assert ai_jobs.claim_ai_job(db, job_id) is True
        assert ai_jobs.record_ai_job_failure(db, job_id, TimeoutError("provider went away")) == (
            ai_jobs.AI_JOB_QUEUED
        )
        row = db.get(AiJob, job_id)
        assert row.status == ai_jobs.AI_JOB_QUEUED and ai_jobs.ai_job_attempts(row) == 1
        assert (row.error or "").startswith("attempt=1/3: TimeoutError")
        assert not ai_jobs.is_dead_lettered(row)

        assert ai_jobs.claim_ai_job(db, job_id) is True
        assert ai_jobs.record_ai_job_failure(db, job_id, TimeoutError("still away")) == (
            ai_jobs.AI_JOB_QUEUED
        )
        assert ai_jobs.ai_job_attempts(db.get(AiJob, job_id)) == 2

        assert ai_jobs.claim_ai_job(db, job_id) is True
        assert (
            ai_jobs.record_ai_job_failure(db, job_id, TimeoutError("gone")) == ai_jobs.AI_JOB_FAILED
        )
        row = db.get(AiJob, job_id)
        assert row.status == ai_jobs.AI_JOB_FAILED
        assert ai_jobs.is_dead_lettered(row), "spent retries must dead-letter, not look retryable"
        assert (row.error or "").startswith("attempt=3/3: TimeoutError")

        # a terminal row is never dispatched again, whatever the sweep sees
        assert ai_jobs.recover_stale_ai_jobs(factory) == []
        assert ai_jobs.claim_ai_job(db, job_id) is False
    finally:
        db.close()
        engine.dispose()


def test_input_shaped_failure_fails_on_the_first_attempt(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path}/terminal.db"
    job_id = _seed_teacher_and_job(db_url, status=ai_jobs.AI_JOB_GENERATING)
    factory, engine = _factory(db_url)
    db = factory()
    try:
        from pydantic import ValidationError

        assert LookupError in ai_jobs.AI_JOB_NON_RETRYABLE
        assert ValidationError in ai_jobs.AI_JOB_NON_RETRYABLE
        exc = LookupError("unsupported generator kind")
        assert ai_jobs.record_ai_job_failure(db, job_id, exc) == ai_jobs.AI_JOB_FAILED
        row = db.get(AiJob, job_id)
        assert row.status == ai_jobs.AI_JOB_FAILED
        assert ai_jobs.ai_job_attempts(row) == 1
        assert not ai_jobs.is_dead_lettered(row), "bad input never retried, so it is not a DLQ case"
    finally:
        db.close()
        engine.dispose()


def test_retry_backoff_gates_and_is_jittered(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path}/backoff.db"
    job_id = _seed_teacher_and_job(db_url, status=ai_jobs.AI_JOB_QUEUED)
    factory, engine = _factory(db_url)
    db = factory()
    try:
        assert ai_jobs.claim_ai_job(db, job_id) is True
        ai_jobs.record_ai_job_failure(db, job_id, TimeoutError("once"))
    finally:
        db.close()

    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        # before the backoff elapses: the sweep must NOT dispatch it
        assert ai_jobs.recover_stale_ai_jobs(factory, now=now) == []
        # after it does
        assert ai_jobs.recover_stale_ai_jobs(factory, now=now + timedelta(seconds=60)) == [job_id]
    finally:
        engine.dispose()

    # jitter: every delay sits inside [ceiling/2, ceiling] and varies, so a
    # fleet of replicas that all saw the same outage does not retry in lockstep
    from bangla_gpt_api.providers.base import JITTER_FLOOR

    policy = ai_jobs.AI_JOB_RETRY_POLICY
    for attempt in range(4):
        ceiling = min(policy.base_seconds * (2**attempt), policy.cap_seconds)
        samples = [policy.delay_seconds(attempt) for _ in range(50)]
        assert all(ceiling * JITTER_FLOOR <= value <= ceiling for value in samples), attempt
        assert len(set(samples)) > 1, "a deterministic delay lets replicas retry in lockstep"
    # ... and the whole chain stays inside the declared worst case
    assert policy.worst_case_seconds() >= sum(
        policy.delay_seconds(n) for n in range(policy.max_retries)
    )


def test_lease_expiry_requeues_with_the_attempt_counted(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path}/lease.db"
    job_id = _seed_teacher_and_job(db_url, status=ai_jobs.AI_JOB_GENERATING, age_seconds=3600)
    factory, engine = _factory(db_url)
    try:
        assert ai_jobs.recover_stale_ai_jobs(factory) == [job_id]
        db = factory()
        try:
            row = db.get(AiJob, job_id)
            assert row.status == ai_jobs.AI_JOB_QUEUED
            assert ai_jobs.ai_job_attempts(row) == 1
            assert "LeaseExpired" in (row.error or "")
        finally:
            db.close()
        # ... and a claim takes it again
        db = factory()
        try:
            assert ai_jobs.claim_ai_job(db, job_id) is True
        finally:
            db.close()
    finally:
        engine.dispose()


def test_fresh_job_is_not_touched_by_the_sweep(tmp_path) -> None:
    """A job queued a second ago is not "stale"; recovery must not preempt it."""
    db_url = f"sqlite:///{tmp_path}/fresh.db"
    job_id = _seed_teacher_and_job(db_url, status=ai_jobs.AI_JOB_QUEUED)
    factory, engine = _factory(db_url)
    try:
        ready = ai_jobs.recover_stale_ai_jobs(factory)
        # fresh queued rows are returned for dispatch (the never-dispatched
        # window), but a generating row with a live lease is not
        assert ready == [job_id]
        db = factory()
        try:
            db.get(AiJob, job_id).status = ai_jobs.AI_JOB_GENERATING
            db.commit()
        finally:
            db.close()
        assert ai_jobs.recover_stale_ai_jobs(factory) == []
    finally:
        engine.dispose()


def test_lease_is_longer_than_the_worst_case_provider_chain() -> None:
    """The lease is derived, not guessed: it must exceed one provider call."""
    from bangla_gpt_api.providers.base import fit_timeout, worst_case_seconds

    settings = Settings(env="test")
    per_attempt = fit_timeout(settings.llm_timeout_seconds, settings.llm_max_retries)
    worst = worst_case_seconds(per_attempt, settings.llm_max_retries)
    assert worst < ai_jobs.AI_JOB_LEASE_SECONDS, (
        f"a live worker could hold its claim longer than the lease ({worst}s)"
    )
