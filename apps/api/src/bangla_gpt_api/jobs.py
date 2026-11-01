"""idempotent scheduled jobs -- one core, two schedulers.

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
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AiJob, JobRun

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def _utc_naive_now() -> datetime:
    # DB datetimes are stored naive-UTC throughout this codebase.
    return datetime.now(UTC).replace(tzinfo=None)


# --- F-007: AiJob lifecycle policy (idempotency, retry, in-flight states) ---
# The policy lives here, next to the scheduled jobs, so the router that
# accepts a job and the sweeper that ages one out read the same constants
# instead of growing their own copies of them.

#: Header a caller sends to make POST /teacher/jobs idempotent.
IDEMPOTENCY_HEADER = "Idempotency-Key"

#: A key shorter than this is a client bug rather than a token: it would
#: make unrelated submissions collide. The ceiling matches the column.
IDEMPOTENCY_KEY_MIN_LENGTH = 8
IDEMPOTENCY_KEY_MAX_LENGTH = 64
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")

#: States where the runner is (or is about to be) doing work. The retention
#: sweep must never delete one of these, however old the row looks.
IN_FLIGHT_STATUSES = ("queued", "generating", "validating")
#: Terminal states: the work is over and the row is history.
TERMINAL_STATUSES = ("ready", "failed")
#: Ceiling for one job-level backoff sleep, matching the provider chain's
#: own ceiling (providers.base.MAX_BACKOFF_SECONDS).
_MAX_JOB_BACKOFF_SECONDS = 4.0


def normalize_idempotency_key(raw: str | None) -> str | None:
    """Validate the optional Idempotency-Key header.

    Returns None when the header is absent (the caller gets no replay
    protection). Raises ValueError for a key that is present but unusable:
    silently dropping it would make the documented replay contract a lie.
    """
    if raw is None:
        return None
    key = raw.strip()
    if not (IDEMPOTENCY_KEY_MIN_LENGTH <= len(key) <= IDEMPOTENCY_KEY_MAX_LENGTH):
        raise ValueError(
            f"{IDEMPOTENCY_HEADER} must be "
            f"{IDEMPOTENCY_KEY_MIN_LENGTH}-{IDEMPOTENCY_KEY_MAX_LENGTH} characters"
        )
    if not _KEY_PATTERN.match(key):
        raise ValueError(f"{IDEMPOTENCY_HEADER} must be URL-safe printable ASCII")
    return key


def find_idempotent_job(
    db: Session,
    *,
    user_id: int,
    kind: str,
    key: str,
    window_minutes: int,
    now: datetime | None = None,
) -> AiJob | None:
    """The job this (user, kind, key) already created inside the window.

    The window bounds how long a key stays replayable: a key older than it
    is a new request. Inside the window the unique index
    (``uq_ai_jobs_idempotency``) is the authority -- a concurrent duplicate
    that misses this read loses the INSERT and replays instead (see the
    IntegrityError handling in POST /teacher/jobs).
    """
    now = now or _utc_naive_now()
    cutoff = now - timedelta(minutes=max(1, window_minutes))
    return (
        db.execute(
            select(AiJob)
            .where(
                AiJob.user_id == user_id,
                AiJob.kind == kind,
                AiJob.idempotency_key == key,
                AiJob.created_at >= cutoff,
            )
            .order_by(AiJob.created_at.desc(), AiJob.id.desc())
        )
        .scalars()
        .first()
    )


def is_transient_failure(exc: BaseException) -> bool:
    """True for failures worth a second attempt at the job level.

    The providers already retry inside one call (timeouts, 5xx, connection
    resets) and raise ``ProviderError`` once that chain is exhausted, so at
    the job level the question is different: was this a flaky upstream, or
    a request the caller has to fix? ``ProviderError`` and the transport
    errors are the flaky class. A bad payload (``DocumentInputError``, a
    pydantic validation error, an unknown kind) and anything unexpected are
    permanent -- retrying them burns provider budget to reproduce the same
    failure.
    """
    from bangla_gpt_api.providers.base import ProviderError

    return isinstance(exc, (ProviderError, TimeoutError, ConnectionError, OSError))


def ai_job_retry_plan(settings: Any) -> tuple[int, tuple[float, ...]]:
    """(max attempts, backoff delays) for one job, read from Settings.

    ``AI_JOB_MAX_ATTEMPTS`` is the total number of runner executions, at
    least 1 (retries disabled). The delays double from
    ``AI_JOB_RETRY_BACKOFF_SECONDS`` and are capped, so a bounded retry
    chain stays inside the same order of magnitude as one provider call
    (``LLM_TOTAL_BUDGET_SECONDS`` 45 s) instead of holding a worker for
    minutes.
    """
    attempts = max(1, int(getattr(settings, "ai_job_max_attempts", 1)))
    base = max(0.0, float(getattr(settings, "ai_job_retry_backoff_seconds", 0.0)))
    delays: list[float] = []
    delay = base
    for _ in range(attempts - 1):
        delays.append(delay)
        delay = min(delay * 2, _MAX_JOB_BACKOFF_SECONDS)
    return attempts, tuple(delays)


def claim_period(db: Session, job: str, period_key: str) -> bool:
    """True when THIS caller owns the period slot; False if already claimed.

    A row whose outcome starts with ``FAILED`` is a failed attempt (the
    job crashed mid-run and marked itself via :func:`mark_period_failed`),
    and the same-day retry it allows is the whole point: the old shape
    claimed its slot BEFORE doing the work, so one mid-job crash
    permanently skipped the period -- the retention purge silently
    retained old chats for a day, the parent digest went silent for a
    week, with nothing on the ledger but an unfinished row. The failed row
    STAYS (the audit trail of what failed when), and the retry overwrites
    it via the natural key.
    """
    existing = db.get(JobRun, (job, period_key))
    if existing is not None:
        if not str(existing.outcome or "").startswith("failed"):
            return False
        # failed attempt: clear the way for the retry (row re-inserted below
        # would collide on the natural key, so delete the stale failure).
        db.delete(existing)
        db.commit()
    db.add(JobRun(job=job, period_key=period_key, started_at=_utc_naive_now()))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def mark_period_failed(db: Session, job: str, period_key: str, error: BaseException) -> None:
    """Record a failed attempt without consuming the period (BE-03 jobs).

    ``finish_period`` normally lands with a counts-outcome; when the job
    body raises, the claim row instead gets a FAILED outcome so the next
    trigger of the same period retries instead of finding a slot that
    looks permanently taken. The exception text is truncated into the
    outcome -- enough to name the failure class, never any content.
    """
    row = db.get(JobRun, (job, period_key))
    if row is not None:
        row.finished_at = _utc_naive_now()
        row.outcome = f"failed:{type(error).__name__}"[:40]
        db.commit()


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
    """Weekly parent digest, at most once per ISO week (counts only)."""
    from bangla_gpt_api.services import parent_digest

    now = now or _utc_naive_now()
    due, key = parent_digest.digest_due(now, "")
    if not due:
        return {"ran": False, "reason": "not_due"}
    db = session_factory()
    try:
        if not claim_period(db, "parent_digest", key):
            return {"ran": False, "reason": "already_ran", "period": key}
        try:
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
        except Exception as exc:
            # BE-03: a mid-job crash must not consume the period -- record
            # the failure and re-raise so the worker logs it; the next
            # trigger retries the same day.
            mark_period_failed(db, "parent_digest", key, exc)
            raise
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
        try:
            students, rows = weakness.refresh_mastery(db)
            finish_period(db, "nightly_rollup", day, f"students={students}")
            return {"ran": True, "period": day, "students": students, "rows": rows}
        except Exception as exc:
            mark_period_failed(db, "nightly_rollup", day, exc)
            raise
    finally:
        db.close()


def run_retention_job(
    session_factory: SessionFactory,
    settings: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """retention sweep, at most once per calendar day. The deletes are
    idempotent (expired-only); the job_runs ledger keeps repeat triggers
    cheap and the outcome auditable (counts in the outcome string, )."""
    from bangla_gpt_api.services.retention import run_retention_sweep

    now = now or _utc_naive_now()
    day = now.strftime("%Y-%m-%d")
    db = session_factory()
    try:
        if not claim_period(db, "retention_sweep", day):
            return {"ran": False, "reason": "already_ran", "period": day}
        try:
            report = run_retention_sweep(db, settings=settings, now=now)
            finish_period(
                db,
                "retention_sweep",
                day,
                f"convs={report['conversations_deleted']} msgs={report['chat_messages_deleted']}",
            )
            return {"ran": True, "period": day, **report}
        except Exception as exc:
            # Completed chunks survive (bounded per-chunk commits, DB-03);
            # the FAILED outcome lets the same day retry from where expiry
            # still stands.
            mark_period_failed(db, "retention_sweep", day, exc)
            raise
    finally:
        db.close()
