"""ARQ worker -- runs the SAME jobs.py functions on a redis cron.

    REDIS_URL=redis://redis:6379/0 JOBS_BACKEND=arq arq worker.WorkerSettings

Why this exists: the web process can run N gunicorn workers, and inline
loops then fire in every worker. With JOBS_BACKEND=arq the web processes
switch their loops off and this single worker owns the schedule. Belt and
braces: every period is still claimed in the job_runs table (jobs.py), so
even a misconfigured mix of inline+arq cannot double-run a period.

Job bodies live ONLY in bangla_gpt_api/jobs.py -- this file is wiring.
``arq`` is imported at module level on purpose (a worker without arq is a
configuration error, not a fallback path); the web app never imports this
module, so the API image does not need the worker extras.

Wiring rules (audit 2026-11-12): every sync body runs through
``asyncio.to_thread`` (arq can only cancel at an await — a directly-called
body made job_timeout dead code and froze the loop the connections live
on); a failed body becomes an :class:`arq.worker.Retry` so the SAME period
retries the way the inline loop does; shutdown disposes the engine; and
startup wires the same observability (redaction filter + Sentry) the web
process gets in ``create_app`` — the worker emits the same job events on a
Friday night that the scheduler logs on Tuesday.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.worker import Retry

from bangla_gpt_api import jobs
from bangla_gpt_api.config import get_settings
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.initialize.observability import configure_observability_with_sentry

logger = logging.getLogger(__name__)

# Schedule mirrors the pure rules in services (single source of truth):
# parent digest -- ISO weeks, Sunday (weekday=6) from 16:00 UTC (~22:00 Dhaka)
# retention -- every day from 20:30 UTC (~02:30 Dhaka, )
# nightly rollup -- every day from 21:00 UTC (~03:00 Dhaka)
DIGEST_WEEKDAY = 6
DIGEST_HOUR_UTC = 16
RETENTION_HOUR_UTC = 20
NIGHTLY_HOUR_UTC = 21

#: arq's default 300s job timeout cannot cover the digest's SMTP fan-out
#: (hundreds of families at a 15s send timeout each), so the default would
#: have killed healthy Sunday runs — with a sync body it just never fired.
#: With threaded bodies it is real, so pin it generously.
_JOB_TIMEOUT_SECONDS = 2 * 60 * 60
#: Same-period retries: 3 attempts, 10 minutes apart. jobs.claim_period
#: keeps the ledger honest across attempts (a failed attempt reopens the
#: period; an orphaned claim inside the lease stays owned).
_MAX_TRIES = 3
_RETRY_DEFER_SECONDS = 10 * 60


async def startup(ctx: dict[str, Any]) -> None:
    # Engines/sessions are built inside the worker, never at import time.
    settings = get_settings()
    # One copy per path: the web process wires logging (redaction filter)
    # and Sentry in create_app; the worker process emits its own job events.
    configure_observability_with_sentry(settings)
    engine = make_engine(settings)
    ctx["engine"] = engine
    ctx["session_factory"] = make_session_factory(engine)
    ctx["settings"] = settings


async def shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await asyncio.to_thread(engine.dispose)


async def _run_period_job(
    ctx: dict[str, Any], runner: Any, job_name: str
) -> dict[str, Any]:
    """Run one sync job body off the event loop, bounded and retryable."""
    try:
        return await asyncio.to_thread(runner, ctx["session_factory"], ctx["settings"])
    except Retry:
        raise
    except Exception as exc:
        # arq retries ONLY an explicit Retry; a bare exception is one-shot,
        # and under cron semantics the period would never fire again in
        # time. Defer so the same period retries (bounded by _MAX_TRIES).
        logger.warning(
            "worker_job_failed",
            extra={"job": job_name, "error": type(exc).__name__},
            exc_info=True,
        )
        raise Retry(defer=_RETRY_DEFER_SECONDS) from exc


async def job_weekly_digest(ctx: dict[str, Any]) -> dict[str, Any]:
    return await _run_period_job(ctx, jobs.run_weekly_digest, "parent_digest")


async def job_nightly_rollup(ctx: dict[str, Any]) -> dict[str, Any]:
    return await _run_period_job(ctx, jobs.run_nightly_rollup, "nightly_rollup")


async def job_retention_sweep(ctx: dict[str, Any]) -> dict[str, Any]:
    return await _run_period_job(ctx, jobs.run_retention_job, "retention_sweep")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    on_startup = staticmethod(startup)
    on_shutdown = staticmethod(shutdown)
    job_timeout = _JOB_TIMEOUT_SECONDS
    max_tries = _MAX_TRIES
    # ClassVar: arq reads these as class attributes; annotating them keeps the
    # mutable defaults from being treated as instance state (RUF012).
    functions: ClassVar[list] = [job_weekly_digest, job_nightly_rollup, job_retention_sweep]
    cron_jobs: ClassVar[list] = [
        cron(job_weekly_digest, weekday=DIGEST_WEEKDAY, hour=DIGEST_HOUR_UTC, minute=5),
        cron(job_retention_sweep, hour=RETENTION_HOUR_UTC, minute=30),
        cron(job_nightly_rollup, hour=NIGHTLY_HOUR_UTC, minute=10),
    ]
