"""S5.4: ARQ worker -- runs the SAME jobs.py functions on a redis cron.

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
"""

from __future__ import annotations

import os
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from bangla_gpt_api import jobs
from bangla_gpt_api.config import get_settings
from bangla_gpt_api.db.session import make_engine, make_session_factory

# Schedule mirrors the pure rules in services (single source of truth):
#   parent digest  -- ISO weeks, Sunday (weekday=6) from 16:00 UTC (~22:00 Dhaka)
#   retention      -- every day from 20:30 UTC (~02:30 Dhaka, S5.8)
#   nightly rollup -- every day from 21:00 UTC (~03:00 Dhaka)
DIGEST_WEEKDAY = 6
DIGEST_HOUR_UTC = 16
RETENTION_HOUR_UTC = 20
NIGHTLY_HOUR_UTC = 21


async def startup(ctx: dict[str, Any]) -> None:
    # Engines/sessions are built inside the worker, never at import time.
    settings = get_settings()
    engine = make_engine(settings)
    ctx["session_factory"] = make_session_factory(engine)
    ctx["settings"] = settings


async def job_weekly_digest(ctx: dict[str, Any]) -> dict[str, Any]:
    return jobs.run_weekly_digest(ctx["session_factory"], ctx["settings"])


async def job_nightly_rollup(ctx: dict[str, Any]) -> dict[str, Any]:
    return jobs.run_nightly_rollup(ctx["session_factory"], ctx["settings"])


async def job_retention_sweep(ctx: dict[str, Any]) -> dict[str, Any]:
    return jobs.run_retention_job(ctx["session_factory"], ctx["settings"])


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    on_startup = staticmethod(startup)
    functions = [job_weekly_digest, job_nightly_rollup, job_retention_sweep]
    cron_jobs = [
        cron(job_weekly_digest, weekday=DIGEST_WEEKDAY, hour=DIGEST_HOUR_UTC, minute=5),
        cron(job_retention_sweep, hour=RETENTION_HOUR_UTC, minute=30),
        cron(job_nightly_rollup, hour=NIGHTLY_HOUR_UTC, minute=10),
    ]
