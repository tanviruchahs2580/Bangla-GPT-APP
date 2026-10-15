"""Lifespan context builder.

Extracted from the monolithic ``main.py`` with one critical change: **no
closure capture** of outer variables. Every dependency is passed explicitly
so the lifespan can be inspected, tested, and refactored independently.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.initialize.schedulers import (
    _run_digest_loop,
    _run_weakness_loop,
)
from bangla_gpt_api.logging_config import json_log

logger = logging.getLogger(__name__)

#: How long shutdown waits for in-flight AI jobs before cancelling them.
#: Comfortably inside gunicorn's ``--graceful-timeout 30`` so the SIGKILL
#: fallback is never what actually ends the wait.
AI_JOB_DRAIN_TIMEOUT_SECONDS = 20.0


async def _drain_ai_jobs(app: FastAPI) -> None:
    """Await every in-flight ``AiJob`` task, then cancel whatever is left.

    Requests dispatch content generation with ``asyncio.create_task`` and
    register the handle on ``AppContext.ai_job_tasks`` so asyncio cannot
    garbage-collect it. That set was never awaited, so on shutdown the worker
    exited with jobs mid-flight and their rows stayed at
    ``status="generating"`` permanently.
    """
    ctx = getattr(app.state, "ctx", None)
    tasks: set = getattr(ctx, "ai_job_tasks", None) or set()
    if not tasks:
        return
    pending = {t for t in tasks if not t.done()}
    json_log(logger, logging.INFO, "ai_jobs_drain_start", in_flight=len(pending))
    if pending:
        try:
            await asyncio.wait(pending, timeout=AI_JOB_DRAIN_TIMEOUT_SECONDS)
        except Exception as exc:  # shutdown must continue regardless
            json_log(logger, logging.WARNING, "ai_jobs_drain_failed", error=type(exc).__name__)
    still_running = {t for t in tasks if not t.done()}
    for task in still_running:
        task.cancel()
    if still_running:
        await asyncio.gather(*still_running, return_exceptions=True)
        json_log(
            logger,
            logging.WARNING,
            "ai_jobs_cancelled_at_shutdown",
            cancelled=len(still_running),
        )
    json_log(logger, logging.INFO, "ai_jobs_drain_complete", tracked=len(tasks))
    tasks.clear()


def build_lifespan(
    settings: Settings,
    provider: object | None,
    fast_provider: object | None,
    session_factory: Callable[[], Session],
    engine: object,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build the lifespan context manager with explicit parameters.

    All lifecycle objects (providers, engine, scheduler tasks) are tracked
    for proper cleanup on shutdown.
    """

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        # --- Startup ---
        digest_task: asyncio.Task[None] | None = None
        weakness_task: asyncio.Task[None] | None = None

        if settings.parent_digest_enabled and settings.jobs_backend != "arq":
            digest_task = asyncio.create_task(
                _run_digest_loop(
                    session_factory,
                    settings,
                    settings.parent_digest_check_minutes,
                )
            )
            json_log(logger, logging.INFO, "parent_digest_scheduler_started")

        if settings.weakness_refresh_enabled and settings.jobs_backend != "arq":
            weakness_task = asyncio.create_task(
                _run_weakness_loop(
                    session_factory,
                    settings,
                    settings.weakness_refresh_check_minutes,
                )
            )
            json_log(logger, logging.INFO, "weakness_refresh_scheduler_started")

        # Store task handles for shutdown
        app.state.digest_task = digest_task
        app.state.weakness_task = weakness_task

        yield  # --- Application runs ---

        # --- Shutdown (graceful) ---
        # 0. Drain in-flight fire-and-forget AI jobs BEFORE anything else.
        #    Content generation is dispatched with create_task and kept alive
        #    by a strong reference on AppContext.ai_job_tasks. Nothing
        #    previously awaited that set, so a rolling deploy SIGKILLed the
        #    worker and every queued job stayed at status="generating"
        #    forever with nothing alerting on it (F-079). The provider client
        #    is closed in step 2, so draining first is also the only order in
        #    which a job can finish successfully.
        await _drain_ai_jobs(app)

        # 1. Cancel scheduler tasks
        for attr, label in (
            ("digest_task", "parent_digest"),
            ("weakness_task", "weakness_refresh"),
        ):
            task = getattr(app.state, attr, None)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                json_log(logger, logging.INFO, f"{label}_task_cancelled")

        # 2. Close provider HTTP clients
        for candidate in (provider, fast_provider):
            closer = getattr(candidate, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception as exc:  # shutdown must continue regardless
                    json_log(
                        logger,
                        logging.WARNING,
                        "provider_close_failed",
                        error=type(exc).__name__,
                    )

        # 3. Dispose DB connection pool
        if engine is not None:
            dispose = getattr(engine, "dispose", None)
            if dispose is not None:
                try:
                    dispose()
                except Exception as exc:  # shutdown must continue regardless
                    json_log(
                        logger,
                        logging.WARNING,
                        "engine_dispose_failed",
                        error=type(exc).__name__,
                    )

    return _lifespan
