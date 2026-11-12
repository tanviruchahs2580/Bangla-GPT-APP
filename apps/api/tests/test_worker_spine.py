"""The arq worker spine: threaded bodies, retryable failures, observability.

Four gaps found by audit: the wrappers called the sync job bodies directly
on the event loop (so arq's job_timeout could never fire at an await, and
a hung SMTP read froze the whole worker); a failed body was one-shot (no
same-period retry under the cron backend); the process ran with NO
app logging setup (INFO events lost, no redaction filter); and nothing
disposed the engine on shutdown.
"""

from __future__ import annotations

import asyncio
import importlib.util
import threading
from pathlib import Path
from typing import Any

import pytest
from arq.worker import Retry

from bangla_gpt_api.config import Settings
from conftest import engine_url

# worker.py sits at apps/api/worker.py -- deliberately outside the package
# (the web app never imports it), so the tests load it by file path.
_APP_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("worker_under_test", _APP_DIR / "worker.py")
worker = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
assert _spec.loader is not None
_spec.loader.exec_module(worker)


@pytest.fixture
def ctx(tmp_path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "worker_spine"),
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    real: dict[str, Any] = {}
    asyncio.run(worker.startup(real))
    yield real
    asyncio.run(worker.shutdown(real))


def test_job_bodies_run_off_the_event_loop(ctx, monkeypatch) -> None:
    """arq's job_timeout can only cancel at an await: a directly-called sync
    body (DB + SMTP) made the timeout dead code and froze the loop."""
    seen = {}

    def on_thread(*args) -> dict:
        seen["main"] = threading.current_thread() is threading.main_thread()
        return {"ok": 1}

    monkeypatch.setattr(worker.jobs, "run_retention_job", on_thread)
    result = asyncio.run(worker.job_retention_sweep(ctx))
    assert result == {"ok": 1}
    assert seen["main"] is False


def test_a_failed_body_becomes_a_bounded_retry(ctx, monkeypatch) -> None:
    """The inline backend retries the same period after a failure; under arq
    a plain exception was one-shot and the period died with the process."""

    def always_fails(*args) -> dict:
        raise RuntimeError("smtp down")

    monkeypatch.setattr(worker.jobs, "run_weekly_digest", always_fails)
    with pytest.raises(Retry):
        asyncio.run(worker.job_weekly_digest(ctx))


def test_settings_pin_timeout_tries_and_shutdown() -> None:
    """The bare defaults (300s / 5 tries / no shutdown hook) were silently
    wrong for digest fan-out; pin the chosen values so they cannot drift."""
    assert worker.WorkerSettings.job_timeout == 2 * 60 * 60
    assert worker.WorkerSettings.max_tries == 3
    assert worker.WorkerSettings.on_shutdown is not None


def test_shutdown_disposes_the_engine(ctx) -> None:
    disposed = {}

    class _Engine:
        def dispose(self) -> None:
            disposed["called"] = True

    ctx["engine"] = _Engine()
    asyncio.run(worker.shutdown(ctx))
    assert disposed.get("called") is True


def test_startup_wires_the_app_observability(ctx, monkeypatch) -> None:
    """The web process configures logging+redaction and Sentry in create_app;
    the worker ran bare (INFO job events lost, no redaction filter). Here
    we can't assert on root-logger global state (pytest owns it), so pin
    the wiring call itself."""
    # startup already ran in the fixture before the patch; verify with a spy.
    calls = []
    monkeypatch.setattr(
        worker, "configure_observability_with_sentry", lambda settings: calls.append(settings)
    )
    fresh: dict[str, Any] = {}
    asyncio.run(worker.startup(fresh))
    assert len(calls) == 1 and calls[0].env == "test"
