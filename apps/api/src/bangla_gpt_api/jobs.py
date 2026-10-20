"""Durable jobs: the scheduled-period ledger, retry policy, unit of work.

**Scheduled jobs** -- one core, two schedulers. The same job functions run
either from the inline loops in the web process (``JOBS_BACKEND=inline``,
default) or from an ARQ worker's cron (``JOBS_BACKEND=arq`` +
``arq worker.WorkerSettings``). Idempotency lives in ONE place so it cannot
drift between schedulers: :func:`claim_period` inserts a (job, period_key) row
into ``job_runs`` whose composite primary key makes a double run -- process
restart, two gunicorn workers racing, web loop plus ARQ cron, retried queue
delivery -- execute each period's side effects at most once. The loser's
INSERT hits IntegrityError and the job skips. This also fixes the pre-5.4
behaviour where schedule state lived in a per-process dict: under
``gunicorn -w N`` every worker kept its own memory and the weekly digest could
go out N times.

**Retry policy (C-17).** :class:`RetryPolicy` is the explicit, jittered policy
for every integration boundary this module touches: the DB (a transient
``OperationalError`` during the period claim), SMTP (``send_mail``'s
documented ``False`` verdict) and the AI-job attempts. The LLM providers use
the same formula from ``providers/base.py``. Jitter is drawn from
``[ceiling * JITTER_FLOOR, ceiling]``, so the declared worst case stays an
upper bound and a fleet of replicas does not retry in lockstep.

**Unit of work (C-11).** :func:`session_scope` is the transaction boundary
every job body runs inside: commit on success, rollback on failure, always
close.

The AiJob row itself -- its state machine, claim, lease, retries and
dead-letter handling (C-04, C-08) -- lives in :mod:`bangla_gpt_api.ai_jobs`;
this module keeps the *scheduled-period* half so neither file becomes the next
god module (C-03).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from bangla_gpt_api.db import clock
from bangla_gpt_api.db.models import JobRun
from bangla_gpt_api.providers.base import JITTER_FLOOR

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
T = TypeVar("T")


def _utc_naive_now() -> datetime:
    # DB datetimes are stored naive-UTC throughout this codebase.
    # E-16 (H-14): the scheduled-period half of the job machinery reads time
    # through the injectable clock seam, so tests can pin the cutoff second
    # without monkeypatching datetime (retention.py and mailer.py are already
    # on the same seam).
    return clock.utcnow()


# --------------------------------------------------------------------------- #
# Retry policy (C-17) -- one explicit policy per integration boundary
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry with jittered exponential backoff for one boundary.

    ``attempts`` counts total tries (1 = no retry). The delay before attempt
    ``n`` (0-based) is drawn uniformly from
    ``[ceiling * JITTER_FLOOR, ceiling]`` with
    ``ceiling = min(base * 2**n, cap)`` -- the same formula the LLM providers
    use, so jitter can only shorten the declared worst case.
    """

    name: str
    attempts: int
    base_seconds: float
    cap_seconds: float

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError(f"{self.name}: attempts must be >= 1")
        if self.base_seconds <= 0 or self.cap_seconds <= 0:
            raise ValueError(f"{self.name}: backoff bounds must be positive")

    @property
    def max_retries(self) -> int:
        return self.attempts - 1

    def delay_seconds(self, attempt: int) -> float:
        ceiling = min(self.base_seconds * (2 ** max(0, attempt)), self.cap_seconds)
        return _JITTER_RNG.uniform(ceiling * JITTER_FLOOR, ceiling)

    def worst_case_seconds(self) -> float:
        """Upper bound of the whole sleep chain (jitter included)."""
        ceilings = [
            min(self.base_seconds * (2**n), self.cap_seconds) for n in range(self.max_retries)
        ]
        return float(sum(ceilings))


#: Transient DB failures (SQLite "database is locked", a dropped Postgres
#: connection) are retried on job-owned sessions. IntegrityError is NOT here:
#: for the claim ledger it is the double-run signal, not a transient fault.
DB_RETRY_POLICY = RetryPolicy(name="db", attempts=3, base_seconds=0.25, cap_seconds=2.0)
DB_RETRY_EXCEPTIONS: tuple[type[Exception], ...] = (OperationalError,)

#: Jitter source for every policy in this module. SystemRandom on purpose: a
#: seeded application RNG (tests, fixtures, a future deterministic mode) would
#: make a retry storm deterministic again, which is the failure mode jitter
#: exists to break. Same reasoning as providers/base._JITTER_RNG.
_JITTER_RNG = random.SystemRandom()

#: SMTP delivery (services/mailer.py returns False on OSError/SMTPException).
#: Deliberately ONE retry, not three: the mailer's ``False`` cannot distinguish
#: a transient relay fault from a permanent one (bad credentials, rejected
#: recipient), and each attempt can cost the full 15s socket timeout, so the
#: policy bounds its own worst case instead of letting a blind retry loop
#: multiply an already slow path. See the handoff note about a typed delivery
#: failure if a true classification ever lands in the mailer.
SMTP_RETRY_POLICY = RetryPolicy(name="smtp", attempts=2, base_seconds=0.5, cap_seconds=2.0)


def _backoff_sleep(attempt: int, policy: RetryPolicy) -> float:
    delay = policy.delay_seconds(attempt)
    time.sleep(delay)
    return delay


def retry_on_error(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[int, float, Exception], None] | None = None,
) -> T:
    """Run ``fn`` under ``policy``; re-raise the last error when the budget is spent.

    Raises immediately for an exception outside ``retry_on``: a permanent
    error must not burn the retry budget.
    """
    for attempt in range(policy.attempts):
        try:
            return fn()
        except retry_on as exc:
            if attempt + 1 >= policy.attempts:
                raise
            delay = _backoff_sleep(attempt, policy)
            if on_retry is not None:
                on_retry(attempt + 1, delay, exc)
    raise AssertionError("unreachable: the loop either returns or raises")


def retry_until_true(
    fn: Callable[[], bool],
    *,
    policy: RetryPolicy,
    on_retry: Callable[[int, float], None] | None = None,
) -> bool:
    """Retry a boolean-returning boundary until it reports success.

    For mailers that report failure as ``False`` instead of raising (the
    documented ``services/mailer.send_mail`` contract): the retry lives here,
    the False contract stays.
    """
    result = False
    for attempt in range(policy.attempts):
        result = fn()
        if result:
            return True
        if attempt + 1 >= policy.attempts:
            break
        delay = _backoff_sleep(attempt, policy)
        if on_retry is not None:
            on_retry(attempt + 1, delay)
    return result


def send_mail_with_retry(
    settings: Any,
    *,
    to: str,
    subject: str,
    body: str,
    policy: RetryPolicy = SMTP_RETRY_POLICY,
    sender: Callable[..., bool] | None = None,
) -> bool:
    """SMTP boundary policy: :data:`SMTP_RETRY_POLICY` around ``send_mail``.

    Returns the mailer's own verdict after the retries are spent, so callers
    keep treating ``False`` as "not delivered" and no new exception surface
    appears. The default sender is imported lazily so the policy can be
    applied elsewhere without tightening this module's import graph.
    """
    if sender is None:
        from bangla_gpt_api.services.mailer import send_mail

        sender = send_mail

    def attempt() -> bool:
        return bool(sender(settings, to=to, subject=subject, body=body))

    def _log(retries: int, delay: float) -> None:
        logger.warning(
            "smtp_retry",
            extra={"op": "smtp", "retries": retries, "delay_seconds": round(delay, 3)},
        )

    return retry_until_true(attempt, policy=policy, on_retry=_log)


# --------------------------------------------------------------------------- #
# Transaction boundary (C-11) -- one unit of work per job run
# --------------------------------------------------------------------------- #


@contextmanager
def session_scope(session_factory: SessionFactory) -> Iterator[Session]:
    """Unit of work for job-owned sessions: commit on success, rollback on
    error, always close.

    The previous ``try/finally: db.close()`` pattern left a failed job's
    transaction open until the connection was returned to the pool and made
    "did this run commit anything?" a per-function question. Here the boundary
    is the block: an exception inside it rolls back everything not already
    committed, so a half-written run is impossible.
    """
    db = session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Scheduled job ledger -- the at-most-once claim
# --------------------------------------------------------------------------- #


def claim_period(db: Session, job: str, period_key: str) -> bool:
    """True when THIS caller owns the period slot; False if already claimed."""
    try:
        _transaction_with_retry(
            db, lambda: db.add(JobRun(job=job, period_key=period_key, started_at=_utc_naive_now()))
        )
        return True
    except IntegrityError:
        # The composite primary key rejected the second claim: another worker,
        # scheduler or restarted process owns this period. NOT retried -- this
        # exception is the double-run signal, not a transient fault.
        db.rollback()
        return False


def finish_period(db: Session, job: str, period_key: str, outcome: str) -> None:
    """Stamp the period's outcome. Commits with the CALLER's unit of work.

    Deliberately not its own transaction: the sweep bodies leave their writes
    pending (``run_retention_sweep`` never commits) and the outcome stamp must
    commit with them. Wrapping this in a rollback-first transaction of its own
    silently discarded the sweep's deletes -- which the nightly-retention test
    caught as "the sweep did not actually execute" before this landed.
    """
    row = db.get(JobRun, (job, period_key))
    if row is None:
        return
    row.finished_at = _utc_naive_now()
    row.outcome = outcome[:40]


def _transaction_with_retry(
    db: Session,
    work: Callable[[], T],
    policy: RetryPolicy = DB_RETRY_POLICY,
) -> T:
    """One unit of work under the explicit DB retry policy (C-17).

    **The whole unit of work is retried, and it starts from a clean
    transaction.** Both halves matter:

    * retrying only the ``commit()`` is worse than useless -- the mandatory
      ``rollback()`` discards pending ORM state, so the retried commit would
      succeed while persisting nothing;
    * the leading ``rollback()`` means ``work`` must contain everything the
      transaction has to write. A caller that leaves its own writes pending
      and then calls a helper that opens one of these transactions has them
      discarded, so this is only ever used at the top of a job body
      (:func:`claim_period` and the three period runners), never as a
      mid-transaction commit helper.

    ``work`` is therefore re-run on each attempt and must be idempotent to
    re-run (a delete sweep by cutoff, a recompute, an insert guarded by a
    primary key). IntegrityError propagates untouched: for the ledger it *is*
    the answer.
    """
    result: T | None = None

    def attempt() -> None:
        nonlocal result
        db.rollback()  # a previous attempt's failed commit must not leak in
        result = work()
        db.commit()

    retry_on_error(
        attempt,
        policy=policy,
        retry_on=DB_RETRY_EXCEPTIONS,
        on_retry=lambda retries, delay, exc: logger.warning(
            "db_transaction_retry",
            extra={"op": "db", "retries": retries, "delay_seconds": round(delay, 3)},
        ),
    )
    # mypy cannot see through the local closure: `attempt` assigns `result =
    # work()` and only ever raises rather than returning early, so a
    # non-raising retry_on_error proves result holds work()'s product, not None.
    return result  # type: ignore[return-value]


def run_weekly_digest(
    session_factory: SessionFactory,
    settings: Any,
    *,
    now: datetime | None = None,
    sender: Callable[..., bool] | None = None,
) -> dict[str, Any]:
    """Weekly parent digest, at most once per ISO week (counts only).

    The SMTP boundary runs under :data:`SMTP_RETRY_POLICY` when a relay is
    configured; with SMTP disabled the sender stays ``None`` so the digest's
    own ``smtp_not_configured`` short-circuit (and its skipped reason) is
    unchanged.
    """
    from bangla_gpt_api.services import parent_digest
    from bangla_gpt_api.services.mailer import smtp_configured

    now = now or _utc_naive_now()
    due, key = parent_digest.digest_due(now, "")
    if not due:
        return {"ran": False, "reason": "not_due"}
    with session_scope(session_factory) as db:
        if not claim_period(db, "parent_digest", key):
            return {"ran": False, "reason": "already_ran", "period": key}
        if sender is None:
            sender = send_mail_with_retry if smtp_configured(settings) else None

        def _run_digest() -> dict[str, Any]:
            stats = parent_digest.run_weekly_digest(settings, db, sender=sender, now=now)
            finish_period(
                db, "parent_digest", key, f"families={stats.families} sent={stats.delivered}"
            )
            return {
                "ran": True,
                "period": key,
                "families": stats.families,
                "delivered": stats.delivered,
                "undelivered": stats.undelivered,
                "skipped": stats.skipped or "",
            }

        return _transaction_with_retry(db, _run_digest)


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
    with session_scope(session_factory) as db:
        if not claim_period(db, "nightly_rollup", day):
            return {"ran": False, "reason": "already_ran", "period": day}

        def _run_rollup() -> dict[str, Any]:
            students, rows = weakness.refresh_mastery(db)
            finish_period(db, "nightly_rollup", day, f"students={students}")
            return {"ran": True, "period": day, "students": students, "rows": rows}

        # refresh_mastery recomputes from the graded log, so re-running it on a
        # retry is a strict no-op (the same idempotence the ledger relies on).
        return _transaction_with_retry(db, _run_rollup)


def run_retention_job(
    session_factory: SessionFactory,
    settings: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """retention sweep, at most once per calendar day. The deletes are
    idempotent (expired-only); the job_runs ledger keeps repeat triggers
    cheap and the outcome auditable (counts in the outcome string, ).

    The sweep leaves its deletes pending on purpose (it never commits, so the
    admin route can run it dry or inside a request transaction). They are
    committed here, in the same unit of work as the ledger outcome.
    """
    from bangla_gpt_api.services.retention import run_retention_sweep

    now = now or _utc_naive_now()
    day = now.strftime("%Y-%m-%d")
    with session_scope(session_factory) as db:
        if not claim_period(db, "retention_sweep", day):
            return {"ran": False, "reason": "already_ran", "period": day}

        def _run_sweep() -> dict[str, Any]:
            report = run_retention_sweep(db, settings=settings, now=now)
            finish_period(
                db,
                "retention_sweep",
                day,
                f"convs={report['conversations_deleted']} msgs={report['chat_messages_deleted']}",
            )
            return {"ran": True, "period": day, **report}

        # The deletes are cutoff-based, so re-running the sweep on a retry
        # deletes the same (still uncommitted) rows again -- idempotent.
        return _transaction_with_retry(db, _run_sweep)
