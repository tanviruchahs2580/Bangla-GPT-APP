"""AiJob lifecycle and durability -- the state machine and the claim.

Split out of ``jobs.py`` when the C-04/C-08 work made that module the largest
non-generated file in the tree (C-03's 500-line rule applies to new code, and
a "jobs" module owning two different jobs would have grown into the next god
module). ``jobs.py`` keeps the *scheduled period* ledger and the shared retry
policy; this module owns the **AiJob** row:

* :data:`AI_JOB_ALLOWED_TRANSITIONS` -- the explicit state machine (C-04), the
  single writer of ``AiJob.status``, with illegal edges raising
  :class:`IllegalAiJobTransition`;
* :func:`claim_ai_job` -- the atomic DB claim (one conditional UPDATE), which
  is also the idempotency key for two replicas racing the same job;
* the lease (:data:`AI_JOB_LEASE_SECONDS`, heartbeat = ``updated_at``),
  :func:`recover_stale_ai_jobs` (kill recovery + due retries) and
  :func:`record_ai_job_failure` (retry with backoff vs terminal failure);
* the dead-letter classification (:func:`is_dead_lettered`).

Attempt accounting has no column of its own (the remediation brief forbids
touching ``db/**``): the count rides the existing, user-visible ``error``
string as ``attempt=N/M: <ExceptionType>`` and is parsed back by
:func:`ai_job_attempts`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import cast

from pydantic import ValidationError
from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AiJob
from bangla_gpt_api.jobs import RetryPolicy, SessionFactory, _utc_naive_now

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# AiJob lifecycle (C-04) -- the explicit state machine
# --------------------------------------------------------------------------- #

AI_JOB_QUEUED = "queued"
AI_JOB_GENERATING = "generating"
AI_JOB_VALIDATING = "validating"
AI_JOB_READY = "ready"
AI_JOB_FAILED = "failed"

#: Every state the lifecycle may hold. Kept equal to the five values the
#: ``ck_ai_jobs_status`` CHECK constraint allows (db/models.py + migration
#: a3c5e7f9b1d3): the code-side machine and the schema-side invariant must
#: agree, and a sixth status may only appear here once the schema admits it.
AI_JOB_STATUSES: frozenset[str] = frozenset(
    {AI_JOB_QUEUED, AI_JOB_GENERATING, AI_JOB_VALIDATING, AI_JOB_READY, AI_JOB_FAILED}
)

#: Terminal states; nothing may leave them.
AI_JOB_TERMINAL_STATUSES: frozenset[str] = frozenset({AI_JOB_READY, AI_JOB_FAILED})

#: The allowed transitions. ``-> queued`` from an in-flight state is the RETRY
#: re-queue (attempt counter lives in ``error``); ``-> failed`` is terminal,
#: either because the input itself is invalid or because the retries are spent
#: (see :data:`AI_JOB_DEAD_LETTER_MARK`).
AI_JOB_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    AI_JOB_QUEUED: frozenset({AI_JOB_GENERATING}),
    AI_JOB_GENERATING: frozenset({AI_JOB_VALIDATING, AI_JOB_QUEUED, AI_JOB_FAILED}),
    AI_JOB_VALIDATING: frozenset({AI_JOB_READY, AI_JOB_QUEUED, AI_JOB_FAILED}),
    AI_JOB_READY: frozenset(),
    AI_JOB_FAILED: frozenset(),
}

#: Statuses from which the runner may take ownership of a job row.
AI_JOB_CLAIMABLE_STATUSES: frozenset[str] = frozenset({AI_JOB_QUEUED})

#: Marker appended to ``error`` when a job is terminally given up on: the
#: dead-letter classification. It rides the existing visible column instead of
#: adding a status the DB CHECK constraint (not this module's to edit) and the
#: web client do not know yet.
AI_JOB_DEAD_LETTER_MARK = "(dead-lettered)"


class IllegalAiJobTransition(ValueError):
    """Raised when code tries to move a job along an edge the table forbids."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"illegal AiJob transition {current!r} -> {target!r}")
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    return target in AI_JOB_ALLOWED_TRANSITIONS.get(current, frozenset())


def transition_ai_job(job: AiJob, target: str) -> None:
    """Apply one allowed transition; raise :class:`IllegalAiJobTransition`.

    Does not commit: the caller owns the unit of work (see
    :func:`session_scope`), so a job can move through several states inside one
    transaction and a failure cannot leave a half-applied lifecycle.
    """
    if target not in AI_JOB_STATUSES:
        raise IllegalAiJobTransition(job.status, target)
    if not can_transition(job.status, target):
        raise IllegalAiJobTransition(job.status, target)
    job.status = target


# --------------------------------------------------------------------------- #
# AiJob durability (C-08) -- claim, lease, retry, dead-letter
# --------------------------------------------------------------------------- #

#: How long a claim stays valid without a heartbeat. Derived, not guessed: the
#: whole provider chain is capped by ``LLM_TOTAL_BUDGET_SECONDS`` (45s) and the
#: document persist is one transaction, so 300s is several times the worst case
#: a live worker can take. ``updated_at`` is the heartbeat.
AI_JOB_LEASE_SECONDS = 300.0

#: Total attempts per job (the first run plus the retries).
AI_JOB_MAX_ATTEMPTS = 3

#: Backoff between attempts: base 4s doubling to 30s, jittered.
AI_JOB_RETRY_POLICY = RetryPolicy(
    name="ai_job", attempts=AI_JOB_MAX_ATTEMPTS, base_seconds=4.0, cap_seconds=30.0
)

#: How often the recovery sweep runs (any replica may run it; the claim is
#: atomic, so extra sweepers are harmless).
AI_JOB_RECOVERY_INTERVAL_SECONDS = 15.0

#: Failures that retrying cannot fix: an unsupported kind or a payload that
#: does not validate is a permanent property of the request. Everything else
#: (provider, transport, transient DB) is retried.
AI_JOB_NON_RETRYABLE: tuple[type[Exception], ...] = (LookupError, ValidationError)

_ATTEMPT_PREFIX = "attempt="


def ai_job_attempts(job: AiJob) -> int:
    """Attempts already spent, parsed from the ``error`` marker.

    ``error`` is the only column that survives without a migration and is
    already user-visible ("attempt=2/3: ProviderError" tells the teacher what
    happened better than a bare type name did).
    """
    error = job.error or ""
    if not error.startswith(_ATTEMPT_PREFIX):
        return 0
    marker = error[len(_ATTEMPT_PREFIX) :].split("/", 1)[0]
    try:
        return max(0, int(marker))
    except ValueError:
        return 0


def _attempt_error(attempt: int, exc_type: str, *, dead_lettered: bool = False) -> str:
    mark = f" {AI_JOB_DEAD_LETTER_MARK}" if dead_lettered else ""
    return f"{_ATTEMPT_PREFIX}{attempt}/{AI_JOB_MAX_ATTEMPTS}: {exc_type}{mark}"[:300]


def is_dead_lettered(job: AiJob) -> bool:
    """True when this job was terminally given up on (the dead-letter case).

    Distinct from a plain ``failed``: an input-shaped failure is the request's
    fault and completes on the first attempt, while a dead-lettered job spent
    every attempt on a transient failure. Operators get the distinction from
    this predicate, the ``ai_job_dead_lettered`` log event and the error text.
    """
    return job.status == AI_JOB_FAILED and AI_JOB_DEAD_LETTER_MARK in (job.error or "")


def ai_job_retry_delay(attempts_spent: int) -> float:
    """Jittered backoff before the next attempt (``attempts_spent`` >= 1)."""
    return AI_JOB_RETRY_POLICY.delay_seconds(max(0, attempts_spent - 1))


def claim_ai_job(db: Session, job_id: str, *, now: datetime | None = None) -> bool:
    """Atomically take ownership of a claimable job row.

    True only for the caller whose conditional UPDATE moved the row out of
    ``queued``/``retrying``. Two processes -- or a process and the recovery
    sweep -- that both try get exactly one True; the loser must not run the
    job. The source statuses come from the transition table, so the claim can
    never be an edge the state machine forbids.
    """
    now = now or _utc_naive_now()
    allowed_sources = sorted(
        status for status in AI_JOB_CLAIMABLE_STATUSES if can_transition(status, AI_JOB_GENERATING)
    )
    result = cast(
        CursorResult,
        db.execute(
            update(AiJob)
            .where(AiJob.id == job_id, AiJob.status.in_(allowed_sources))
            .values(status=AI_JOB_GENERATING, updated_at=now)
        ),
    )
    db.commit()
    return int(result.rowcount) == 1


def ai_job_still_ours(db: Session, job_id: str) -> bool:
    """Fencing check: is this attempt still the owner of the row?

    A worker whose lease expired (the sweep re-queued the row, or another
    replica claimed it) must not persist its result. Callers abort the attempt
    when this returns False.
    """
    db.expire_all()
    job = db.get(AiJob, job_id)
    return job is not None and job.status in (AI_JOB_GENERATING, AI_JOB_VALIDATING)


def record_ai_job_failure(
    db: Session, job_id: str, exc: BaseException, *, now: datetime | None = None
) -> str:
    """Failure handler: re-queue while attempts remain, else terminal.

    Returns the status the row now holds (``queued`` for a scheduled retry,
    ``failed`` for a terminal outcome, or ``"gone"`` when the row vanished).
    Input-shaped errors fail on the first attempt; transient ones are retried
    up to :data:`AI_JOB_MAX_ATTEMPTS` and then dead-lettered, so a permanently
    broken dependency cannot retry forever.
    """
    now = now or _utc_naive_now()
    job = db.get(AiJob, job_id)
    if job is None:
        return "gone"
    attempt = ai_job_attempts(job) + 1
    retryable = not isinstance(exc, AI_JOB_NON_RETRYABLE)
    if retryable and attempt < AI_JOB_MAX_ATTEMPTS:
        target = AI_JOB_QUEUED  # scheduled retry; the sweep re-dispatches it
        job.error = _attempt_error(attempt, type(exc).__name__)
        event = "ai_job_retry_scheduled"
    else:
        target = AI_JOB_FAILED
        dead_lettered = retryable  # only a spent retry budget is a dead letter
        job.error = _attempt_error(attempt, type(exc).__name__, dead_lettered=dead_lettered)
        event = "ai_job_dead_lettered" if dead_lettered else "ai_job_failed"
    transition_ai_job(job, target)
    job.updated_at = now
    db.commit()
    logger.warning(event, extra={"op": "ai_job", "job_id": job_id, "attempt": attempt})
    return target


def abandon_ai_job(db: Session, job_id: str, reason: str, *, now: datetime | None = None) -> None:
    """Dead-letter a job that cannot be completed at all (no owner, no actor)."""
    now = now or _utc_naive_now()
    job = db.get(AiJob, job_id)
    if job is None or job.status in AI_JOB_TERMINAL_STATUSES:
        return
    job.error = f"abandoned: {reason} {AI_JOB_DEAD_LETTER_MARK}"[:300]
    transition_ai_job(job, AI_JOB_FAILED)
    job.updated_at = now
    db.commit()
    logger.warning(
        "ai_job_dead_lettered",
        extra={"op": "ai_job", "job_id": job_id, "reason": reason},
    )


def recover_stale_ai_jobs(
    session_factory: SessionFactory,
    *,
    now: datetime | None = None,
    lease_seconds: float = AI_JOB_LEASE_SECONDS,
) -> list[str]:
    """Recovery sweep. Returns the job ids that should be dispatched now.

    Three stranded shapes are covered, all of which used to be permanent:

    * **expired lease** -- ``generating``/``validating`` rows whose heartbeat
      is older than the lease belonged to a worker that was killed (rolling
      deploy, OOM, SIGKILL). They go back to ``queued``, or are dead-lettered
      once attempts are spent -- which is what makes a hard kill either resume
      or fail *visibly*. The lease itself was the wait, so these dispatch
      immediately.
    * **due retry** -- retried rows (attempt counter in ``error``) whose
      jittered backoff has elapsed.
    * **never dispatched** -- a ``queued`` row with no attempts spent whose
      process died between the commit and the ``create_task``.
    """
    now = now or _utc_naive_now()
    ready: list[str] = []
    db = session_factory()
    try:
        stale = (
            db.execute(
                select(AiJob).where(
                    AiJob.status.in_((AI_JOB_GENERATING, AI_JOB_VALIDATING)),
                    AiJob.updated_at < now - timedelta(seconds=lease_seconds),
                )
            )
            .scalars()
            .all()
        )
        for job in stale:
            attempt = ai_job_attempts(job) + 1
            if attempt >= AI_JOB_MAX_ATTEMPTS:
                abandon_ai_job(db, job.id, "retries spent after lost leases", now=now)
                continue
            job.error = _attempt_error(attempt, "LeaseExpired")
            transition_ai_job(job, AI_JOB_QUEUED)
            job.updated_at = now
            ready.append(job.id)
            logger.warning(
                "ai_job_lease_expired",
                extra={"op": "ai_job", "job_id": job.id, "attempt": attempt},
            )
        queued = db.execute(select(AiJob).where(AiJob.status == AI_JOB_QUEUED)).scalars().all()
        for job in queued:
            if job.id in ready:
                continue
            attempts = ai_job_attempts(job)
            if attempts == 0:
                ready.append(job.id)  # never dispatched: nothing to wait for
                continue
            elapsed = (now - job.updated_at).total_seconds()
            if elapsed >= ai_job_retry_delay(attempts):
                ready.append(job.id)
        db.commit()
    finally:
        db.close()
    return sorted(ready)
