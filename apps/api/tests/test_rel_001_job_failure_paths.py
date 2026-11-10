"""REL-001: a runner failure OUTSIDE the generator call must fail the job.

The runner's try/except used to cover only the generator call: `_load` and the
persistence hop after a successful generation sat outside it, so an exception
there propagated out of the detached task. The row stayed
`generating`/`validating` -- a state the retention sweep deliberately never
deletes (jobs.IN_FLIGHT_STATUSES) -- no `ai_job_failed` line was written, and
the done-callback never retrieved the task's exception either.

These tests inject a failure at each hop and assert the row ends terminal
(`failed` + the exception TYPE name) with a matching structured log line, plus
the residual case the done-callback exists for: a failure the runner's own
failure handling cannot record.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiJob, User
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers import workspace
from conftest import engine_url, poll_until

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = "\u0995\u09cb\u09b7"
WORKSHEET_BODY = {"class_level": 6, "subject": "science", "chapter": CHAPTER}


def _settings(tmp_path, name: str) -> Settings:
    return Settings(
        env="test",
        database_url=engine_url(tmp_path, name),
        jwt_secret=SECRET,
        ai_job_max_attempts=1,
    )


@pytest.fixture
def persist_env(tmp_path):
    """App + session factory, built in the setup phase.

    `create_app` configures logging (``configure_logging`` clears the root
    logger's handlers), so it must not run inside the test body or pytest's
    caplog handler would be gone before the assert.
    """
    settings = _settings(tmp_path, "rel001_persist")
    factory = make_session_factory(make_engine(settings))
    return create_app(settings), factory


@pytest.fixture
def load_env(tmp_path):
    settings = _settings(tmp_path, "rel001_load")
    factory = make_session_factory(make_engine(settings))
    return create_app(settings), factory


@pytest.fixture
def callback_env(tmp_path):
    settings = _settings(tmp_path, "rel001_callback")
    return create_app(settings), None


def _headers(client: TestClient, email: str) -> dict:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teach", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _events(caplog, event: str) -> list[dict]:
    """Structured json_log lines carrying this event name."""
    out: list[dict] = []
    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("event") == event:
            out.append(payload)
    return out


def _wait_settled(client: TestClient, headers: dict, job_id: str, timeout: float = 30.0) -> dict:
    last: dict = {}

    def settled() -> dict | None:
        res = client.get(f"/teacher/jobs/{job_id}", headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        last.update(body)
        return body if body["status"] in ("ready", "failed") else None

    return poll_until(settled, timeout=timeout, describe=lambda: f"job never settled: {last}")


def _seed_queued_job(factory) -> str:
    """A queued AiJob + its owner, via the app's own session factory."""
    job_id = str(uuid4())
    with factory() as session:
        user = User(email=f"{job_id[:8]}@example.test", password_hash="x", role="teacher")
        session.add(user)
        session.flush()
        session.add(
            AiJob(
                id=job_id,
                user_id=user.id,
                kind="worksheet",
                status="queued",
                payload=dict(WORKSHEET_BODY),
            )
        )
        session.commit()
    return job_id


def test_persistence_db_failure_fails_the_job_and_logs(persist_env, monkeypatch, caplog) -> None:
    """Generation succeeds, the persist hop raises: the job must fail visibly."""
    app, factory = persist_env

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(workspace, "_persist_document", _boom)
    caplog.set_level(logging.WARNING)
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            headers = _headers(client, "rel001-persist@example.test")
            res = client.post(
                "/teacher/jobs",
                json={"kind": "worksheet", "payload": WORKSHEET_BODY},
                headers=headers,
            )
            assert res.status_code == 202, res.text
            job_id = res.json()["id"]
            done = _wait_settled(client, headers, job_id)

    assert done["status"] == "failed", done
    assert done["error"] == "RuntimeError"
    with factory() as session:
        row = session.get(AiJob, job_id)
        assert row is not None
        assert row.status == "failed", "the row would sit at `validating` forever"
        assert row.error == "RuntimeError"
    failed = _events(caplog, "ai_job_failed")
    assert any(
        entry.get("job_id") == job_id and entry.get("error_type") == "RuntimeError"
        for entry in failed
    ), failed
    # The failure is on the record, so the crash callback must NOT have fired.
    assert not _events(caplog, "ai_job_task_crashed")


class _OneShotCommitFailure:
    """A session proxy whose FIRST commit raises (a failing ``_ai_job_load``).

    Delegates everything else to the real session, so the runner's failure
    write afterwards works normally -- which is the property under test: a
    load failure must not leave the row non-terminal.
    """

    def __init__(self, session) -> None:
        self._session = session
        self._raised = False

    def commit(self):
        if not self._raised:
            self._raised = True
            raise RuntimeError("simulated load commit failure")
        return self._session.commit()

    def __getattr__(self, name):
        return getattr(self._session, name)


def test_load_commit_failure_fails_the_job_and_logs(load_env, caplog) -> None:
    """`_ai_job_load` raising must be handled like any other run failure."""
    app, factory = load_env
    job_id = _seed_queued_job(factory)

    ctx = app.state.ctx
    real_factory = ctx.session_factory
    ctx.session_factory = lambda: _OneShotCommitFailure(real_factory())
    caplog.set_level(logging.WARNING)
    with caplog.at_level(logging.WARNING):
        asyncio.run(workspace._execute_ai_job(ctx, job_id))

    with factory() as session:
        row = session.execute(select(AiJob).where(AiJob.id == job_id)).scalar_one()
        assert row.status == "failed", "a failed load left the job queued/generating"
        assert row.error == "RuntimeError"
        assert row.attempts == 1
    failed = _events(caplog, "ai_job_failed")
    assert any(
        entry.get("job_id") == job_id and entry.get("error_type") == "RuntimeError"
        for entry in failed
    ), failed


def test_task_exception_is_logged_by_the_done_callback(callback_env, monkeypatch, caplog) -> None:
    """A failure the runner cannot record must still be observable.

    Here the failure WRITE itself raises (a broken analytics insert), so
    nothing the runner does can mark or log the job: the exception reaches the
    task's done-callback, which logs it. That callback was previously a bare
    `ai_job_tasks.discard`, which never retrieved the exception.
    """
    app, _factory = callback_env

    def _boom(*args, **kwargs):
        raise RuntimeError("analytics write exploded")

    monkeypatch.setattr(workspace, "_record_analytics", _boom)
    caplog.set_level(logging.ERROR)
    with caplog.at_level(logging.ERROR):
        with TestClient(app) as client:
            headers = _headers(client, "rel001-callback@example.test")
            res = client.post(
                "/teacher/jobs",
                json={"kind": "totally_bogus_kind", "payload": {}},
                headers=headers,
            )
            assert res.status_code == 202, res.text
            job_id = res.json()["id"]
            # The callback discards the task handle (and logs before doing
            # anything else), so an empty set means the task is finished.
            poll_until(
                lambda: True if not app.state.ctx.ai_job_tasks else None,
                timeout=30.0,
                describe=lambda: "detached job task never finished",
            )

    crashed = _events(caplog, "ai_job_task_crashed")
    assert any(
        entry.get("job_id") == job_id and entry.get("error_type") == "RuntimeError"
        for entry in crashed
    ), crashed
