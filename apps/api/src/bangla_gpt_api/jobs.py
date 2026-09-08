"""S5.4: idempotent scheduled jobs -- one core, two schedulers.

The same job functions run either from the inline loops in the web process
(``JOBS_BACKEND=inline``, default) or from an ARQ worker's cron
(``JOBS_BACKEND=arq`` + ``arq worker.WorkerSettings``). Idempotency lives in
ONE place so it cannot drift between schedulers: ``claim_period`` inserts a
(job, period_key) row into ``job_runs`` whose composite primary key makes a
double run -- process restart, two gunicorn workers racing, web loop plus
ARQ cron, retried queue delivery -- execute each period's side effects at
most once. The loser's INSERT hits IntegrityError and the job skips.

This also fixes the pre-5.4 behaviour where schedule state lived in a
per-process dict: under ``gunicorn -w N`` every worker kept its own memory
and the weekly digest could go out N times.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import JobRun

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def _utc_naive_now() -> datetime:
    # DB datetimes are stored naive-UTC throughout this codebase.
    return datetime.now(UTC).replace(tzinfo=None)


def claim_period(db: Session, job: str, period_key: str) -> bool:
    """True when THIS caller owns the period slot; False if already claimed."""
    db.add(JobRun(job=job, period_key=period_key, started_at=_utc_naive_now()))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def finish_period(db: Session, job: str, period_key: str, outcome: str) -> None:
    row = db.get(JobRun, (job, period_key))
    if row is not None:
        row.finished_at = _utc_naive_now()
        row.outcome = outcome[:40]
        db.commit()


def run_weekly_digest(
    session_factory: SessionFactory,
    settings: Any,
    *,
    now: datetime | None = None,
    sender: Callable[..., bool] | None = None,
) -> dict[str, Any]:
    """Weekly parent digest, at most once per ISO week (R11: counts only)."""
    from bangla_gpt_api.services import parent_digest

    now = now or _utc_naive_now()
    due, key = parent_digest.digest_due(now, "")
    if not due:
        return {"ran": False, "reason": "not_due"}
    db = session_factory()
    try:
        if not claim_period(db, "parent_digest", key):
            return {"ran": False, "reason": "already_ran", "period": key}
        stats = parent_digest.run_weekly_digest(settings, db, sender=sender, now=now)
        outcome = f"families={stats.families} sent={stats.delivered}"
        finish_period(db, "parent_digest", key, outcome)
        return {
            "ran": True,
            "period": key,
            "families": stats.families,
            "delivered": stats.delivered,
            "undelivered": stats.undelivered,
            "skipped": stats.skipped or "",
        }
    finally:
        db.close()


def run_nightly_rollup(
    session_factory: SessionFactory,
    settings: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Nightly mastery rollup, at most once per calendar day (pure recompute,
    so even the ledger table makes concurrent double runs a strict no-op)."""
    from bangla_gpt_api.services import weakness

    now = now or _utc_naive_now()
    due, day = weakness.nightly_due(now, "")
    if not due:
        return {"ran": False, "reason": "not_due"}
    db = session_factory()
    try:
        if not claim_period(db, "nightly_rollup", day):
            return {"ran": False, "reason": "already_ran", "period": day}
        students, rows = weakness.refresh_mastery(db)
        finish_period(db, "nightly_rollup", day, f"students={students}")
        return {"ran": True, "period": day, "students": students, "rows": rows}
    finally:
        db.close()


def run_retention_job(
    session_factory: SessionFactory,
    settings: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """S5.8 retention sweep, at most once per calendar day. The deletes are
    idempotent (expired-only); the job_runs ledger keeps repeat triggers
    cheap and the outcome auditable (counts in the outcome string, R11)."""
    from bangla_gpt_api.services.retention import run_retention_sweep

    now = now or _utc_naive_now()
    day = now.strftime("%Y-%m-%d")
    db = session_factory()
    try:
        if not claim_period(db, "retention_sweep", day):
            return {"ran": False, "reason": "already_ran", "period": day}
        report = run_retention_sweep(db, settings=settings, now=now)
        finish_period(
            db,
            "retention_sweep",
            day,
            f"convs={report['conversations_deleted']} msgs={report['chat_messages_deleted']}",
        )
        return {"ran": True, "period": day, **report}
    finally:
        db.close()
