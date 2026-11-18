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
import time
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.worker import Retry

from bangla_gpt_api import jobs
from bangla_gpt_api.config import get_settings
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.initialize.observability import configure_observability_with_sentry
from bangla_gpt_api.metrics import REGISTRY, WORKER_JOB_DURATION_SECONDS, WORKER_JOBS_TOTAL

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


def _start_worker_metrics_server(settings: Any) -> None:
    """Expose the worker registry on WORKER_METRICS_PORT (0 = disabled).

    The worker published no metrics at all: job outcomes lived only in log
    lines, so a silently failing retention sweep was found by users instead
    of by an alert (2026-11-17 audit P1-2). ``start_http_server`` runs a
    daemon thread serving ``bangla_gpt_api.metrics.REGISTRY`` — the same
    registry the API process uses, so dashboards read one metric vocabulary.
    """
    port = int(getattr(settings, "worker_metrics_port", 0) or 0)
    if port <= 0:
        return
    from prometheus_client import start_http_server

    start_http_server(port, registry=REGISTRY)
    logger.info("worker_metrics_started", extra={"op": "worker", "port": port})


async def startup(ctx: dict[str, Any]) -> None:
    # Engines/sessions are built inside the worker, never at import time.
    settings = get_settings()
    # One copy per path: the web process wires logging (redaction filter)
    # and Sentry in create_app; the worker process emits its own job events.
    configure_observability_with_sentry(settings)
    _start_worker_metrics_server(settings)
    engine = make_engine(settings)
    ctx["engine"] = engine
    ctx["session_factory"] = make_session_factory(engine)
    ctx["settings"] = settings


async def shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await asyncio.to_thread(engine.dispose)


async def _run_period_job(ctx: dict[str, Any], runner: Any, job_name: str) -> dict[str, Any]:
    """Run one sync job body off the event loop, bounded and retryable.

    Every run is metered: ``bgpt_worker_jobs_total{job, outcome}`` (outcome
    is success, failed, retry for a body's own self-defer, or cancelled —
    arq's job_timeout cancels at the await, and a cancelled run must not
    count as a success) and one ``bgpt_worker_job_duration_seconds``
    observation. The counters are the alertable signal (WorkerJobsFailing in
    deploy/prometheus/alerts.yml); the job_runs ledger stays the per-period
    audit trail.
    """
    outcome = "success"
    started = time.perf_counter()
    try:
        return await asyncio.to_thread(runner, ctx["session_factory"], ctx["settings"])
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Retry:
        outcome = "retry"
        raise
    except Exception as exc:
        # arq retries ONLY an explicit Retry; a bare exception is one-shot,
        # and under cron semantics the period would never fire again in
        # time. Defer so the same period retries (bounded by _MAX_TRIES).
        outcome = "failed"
        logger.warning(
            "worker_job_failed",
            extra={"job": job_name, "error": type(exc).__name__},
            exc_info=True,
        )
        raise Retry(defer=_RETRY_DEFER_SECONDS) from exc
    finally:
        WORKER_JOB_DURATION_SECONDS.labels(job=job_name).observe(
            max(0.0, time.perf_counter() - started)
        )
        WORKER_JOBS_TOTAL.labels(job=job_name, outcome=outcome).inc()


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
