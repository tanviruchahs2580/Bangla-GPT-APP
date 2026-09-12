"""Background scheduler loops with health monitoring.

Extracted from the monolithic ``main.py`` and enhanced with:
- Exponential backoff on consecutive failures
- ``asyncio.CancelledError`` handling for graceful shutdown
- Health status tracking (max_failures threshold)

Each loop is a standalone async function that receives
``session_factory`` and ``settings`` as parameters.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.jobs import (
    run_nightly_rollup,
    run_weekly_digest,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_CONSECUTIVE_FAILURES = 10
_BASE_BACKOFF_SECONDS = 60
_MAX_BACKOFF_SECONDS = 3600  # 1 hour cap


def _exponential_backoff(consecutive_failures: int) -> int:
    """Exponential backoff with cap: base * 2^n, capped at _MAX_BACKOFF."""
    return min(_BASE_BACKOFF_SECONDS * (2**consecutive_failures), _MAX_BACKOFF_SECONDS)


# ---------------------------------------------------------------------------
# Parent digest loop
# ---------------------------------------------------------------------------


async def _run_digest_loop(
    session_factory: Callable[[], Session],
    settings: Settings,
    check_interval: int,
) -> None:
    """Weekly parent digest scheduler with health monitoring.

    Runs once per ISO week (Sunday ~22:00 Dhaka) when ``digest_due`` is True.
    Reads only aggregates (never conversation content).
    """
    consecutive_failures = 0

    while True:
        try:
            result = await asyncio.to_thread(run_weekly_digest, session_factory, settings)
            if result.get("ran"):
                consecutive_failures = 0
                from bangla_gpt_api.logging_config import json_log

                json_log(logger, logging.INFO, "parent_digest_run", **result)
        except asyncio.CancelledError:
            logger.info("parent_digest_scheduler_cancelled")
            return  # graceful shutdown
        except Exception as exc:
            consecutive_failures += 1
            from bangla_gpt_api.logging_config import json_log

            json_log(
                logger,
                logging.WARNING,
                "parent_digest_error",
                error=str(exc)[:200],
                consecutive_failures=consecutive_failures,
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "parent_digest_exceeded_max_failures",
                    extra={"op": "health", "consecutive": consecutive_failures},
                )

        wait_seconds = (
            _exponential_backoff(consecutive_failures)
            if consecutive_failures > 0
            else max(1, check_interval) * 60
        )
        await asyncio.sleep(wait_seconds)


# ---------------------------------------------------------------------------
# Weakness refresh loop
# ---------------------------------------------------------------------------


async def _run_weakness_loop(
    session_factory: Callable[[], Session],
    settings: Settings,
    check_interval: int,
) -> None:
    """Nightly mastery rollup scheduler with health monitoring."""
    consecutive_failures = 0

    while True:
        try:
            result = await asyncio.to_thread(run_nightly_rollup, session_factory, settings)
            if result.get("ran"):
                consecutive_failures = 0
                from bangla_gpt_api.logging_config import json_log

                json_log(logger, logging.INFO, "weakness_refresh_run", **result)
        except asyncio.CancelledError:
            logger.info("weakness_refresh_scheduler_cancelled")
            return  # graceful shutdown
        except Exception as exc:
            consecutive_failures += 1
            from bangla_gpt_api.logging_config import json_log

            json_log(
                logger,
                logging.WARNING,
                "weakness_refresh_error",
                error=str(exc)[:200],
                consecutive_failures=consecutive_failures,
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "weakness_refresh_exceeded_max_failures",
                    extra={"op": "health", "consecutive": consecutive_failures},
                )

        wait_seconds = (
            _exponential_backoff(consecutive_failures)
            if consecutive_failures > 0
            else max(1, check_interval) * 60
        )
        await asyncio.sleep(wait_seconds)
