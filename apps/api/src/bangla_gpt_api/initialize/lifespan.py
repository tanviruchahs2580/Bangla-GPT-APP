"""Lifespan context builder.

Extracted from the monolithic ``main.py`` with one critical change: **no
closure capture** of outer variables.  Every dependency is passed explicitly
so the lifespan can be inspected, tested, and refactored independently.
"""

from __future__ import annotations

import asyncio
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
        # 1. Cancel scheduler tasks
        for attr, label in (
            ("digest_task", "parent_digest"),
            ("weakness_task", "weakness_refresh"),
        ):
            task = getattr(app.state, attr, None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                json_log(logger, logging.INFO, f"{label}_task_cancelled")

        # 2. Close provider HTTP clients
        for candidate in (provider, fast_provider):
            closer = getattr(candidate, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:
                    pass

        # 3. Dispose DB connection pool
        if engine is not None:
            dispose = getattr(engine, "dispose", None)
            if dispose is not None:
                try:
                    dispose()
                except Exception:
                    pass

    return _lifespan
