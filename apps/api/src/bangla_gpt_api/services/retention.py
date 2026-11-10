"""Retention policy job (shared core).

Single implementation used by BOTH:
* POST /admin/maintenance/purge (admin-triggered; dry_run=true = report-only
  for compliance evidence, dry_run=false = sweep + audit), and
* the nightly arq job (jobs.run_retention_sweep -> cron in worker.py).

Everything is counts-only: the report and the audit row may say HOW
MANY rows expired, never what they contained.

Deletion batching (DB-03): every large delete runs in bounded chunks with
a commit per chunk. The first shape of this job selected ALL expired ids
and issued one mega-``DELETE ... WHERE id IN (...)`` in one transaction —
a WAL burst and lock window that grew with the whole table, plus a
SQLite variable-count ceiling. The chunk size bounds both the lock
window and the transaction, so a mid-sweep crash leaves smaller
per-chunk transactions behind instead of one unbounded one.

Chat aging (DAT-001): every row is aged by its OWN timestamp. The first
shape aged a conversation by ``Conversation.created_at`` — written once at
creation and never refreshed — and then deleted every message of that
conversation with no timestamp filter, while the client reuses one
conversation per student until "New chat". The first sweep after a thread
passed the window therefore deleted turns sent that same day. Messages now
expire on ``chat_messages.created_at``, and a conversation row goes only
once it has nothing inside the window left.

Id-list paging (DAT-002): no statement may bind an unbounded number of
variables. The first shape loaded every expired conversation id into one
Python list and re-bound the whole list on each chunk; above the engine
ceiling (32766 on SQLite, 65535 on Postgres) the first chunk raised
``too many SQL variables`` and the identical retry meant the sweep never
drained. Ids are now consumed one chunk at a time.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    AiJob,
    AiUsage,
    AnalyticsEventRow,
    AnswerLog,
    ChatMessage,
    Conversation,
    EmailVerification,
    ParentInvite,
    PasswordReset,
)
from bangla_gpt_api.jobs import TERMINAL_STATUSES

# Token/verification/invite rows keep a 30-day grace window after expiry
# (audit/replay window); chat follows the configured retention days.
TOKEN_GRACE_DAYS = 30

#: Rows deleted per chunk/transaction. Small enough to bound the write
#: lock on a loaded production DB (and comfortably above the SQLite
#: variable-count ceiling per statement), large enough that sweep runtime
#: stays dominated by actual expiry rather than per-chunk overhead.
DELETE_CHUNK = 5_000


def _expired_message_where(cutoff: datetime) -> Any:
    """A chat turn expires on its OWN ``created_at`` (DAT-001)."""
    return ChatMessage.created_at < cutoff


def _message_inside_window_exists(cutoff: datetime) -> Any:
    """Correlated EXISTS: this conversation holds a message inside the window."""
    return (
        select(ChatMessage.id)
        .where(
            ChatMessage.conversation_id == Conversation.id,
            ChatMessage.created_at >= cutoff,
        )
        .exists()
    )


def _expired_conversation_where(cutoff: datetime) -> Any:
    """A conversation expires when nothing of it is left inside the window.

    That is: no message younger than the cutoff (the message sweep above has
    emptied it, or it never had one) AND its own ``created_at`` outside the
    window. The second half is what spares an empty conversation the UI has
    just created but not yet posted to — a brand-new "New chat" row must
    survive a nightly sweep that runs between the two requests.

    Both the dry-run report and the sweep use this one predicate, so the
    compliance report cannot drift from what the sweep actually deletes.
    """
    return (Conversation.created_at < cutoff) & ~_message_inside_window_exists(cutoff)


def retention_report(
    db: Session,
    *,
    now: datetime,
    chat_retention_days: int,
    analytics_retention_days: int | None = None,
    answer_log_retention_days: int | None = None,
    ai_usage_retention_days: int | None = None,
    ai_jobs_retention_days: int | None = None,
) -> dict[str, int]:
    """Counts of rows the sweep WOULD delete (no writes)."""
    chat_cutoff = now - timedelta(days=chat_retention_days)
    token_cutoff = now - timedelta(days=TOKEN_GRACE_DAYS)
    analytics_days = (
        chat_retention_days if analytics_retention_days is None else (analytics_retention_days)
    )
    analytics_cutoff = now - timedelta(days=analytics_days)
    answer_days = 730 if answer_log_retention_days is None else (answer_log_retention_days)
    answer_cutoff = now - timedelta(days=answer_days)
    usage_days = 365 if ai_usage_retention_days is None else (ai_usage_retention_days)
    usage_cutoff = now - timedelta(days=usage_days)
    jobs_days = 30 if ai_jobs_retention_days is None else (ai_jobs_retention_days)
    jobs_cutoff = now - timedelta(days=jobs_days)

    # DAT-001: chat rows age on their own timestamps. A conversation created
    # long ago but still in use is not expired and its current turns are not
    # collateral -- only a conversation with nothing left inside the window is
    # counted (and then deleted) as gone.
    conversations = db.execute(
        select(func.count(Conversation.id)).where(_expired_conversation_where(chat_cutoff))
    ).scalar_one()
    messages = db.execute(
        select(func.count(ChatMessage.id)).where(_expired_message_where(chat_cutoff))
    ).scalar_one()
    resets = db.execute(
        select(func.count(PasswordReset.id)).where(PasswordReset.expires_at < token_cutoff)
    ).scalar_one()
    verifications = db.execute(
        select(func.count(EmailVerification.id)).where(EmailVerification.expires_at < token_cutoff)
    ).scalar_one()
    invites = db.execute(
        select(func.count(ParentInvite.id)).where(
            ParentInvite.expires_at < token_cutoff,
            ParentInvite.used_at.isnot(None),
        )
    ).scalar_one()
    # F-058: the analytics trail was documented as swept but never was.
    analytics_events = db.execute(
        select(func.count(AnalyticsEventRow.id)).where(
            AnalyticsEventRow.created_at < analytics_cutoff
        )
    ).scalar_one()
    # DB-04: the graded-answer record ages on its own timestamp (backfilled
    # from the attempt for rows written before the column existed).
    answer_log = db.execute(
        select(func.count(AnswerLog.id)).where(AnswerLog.created_at < answer_cutoff)
    ).scalar_one()
    ai_usage = db.execute(
        select(func.count(AiUsage.id)).where(AiUsage.created_at < usage_cutoff)
    ).scalar_one()
    # F-007: ai_jobs rows were only ever removed by account erasure, so the
    # payload/result JSON grew without bound. Aged by updated_at (not
    # created_at): a job that was retried or finished recently is not old
    # history just because it was accepted a while ago. In-flight rows are
    # excluded -- an old-looking queued row is a stuck job for the startup
    # reaper, never something the sweeper silently deletes.
    ai_jobs = db.execute(
        select(func.count(AiJob.id)).where(
            AiJob.status.in_(TERMINAL_STATUSES),
            AiJob.updated_at < jobs_cutoff,
        )
    ).scalar_one()
    return {
        "conversations_deleted": int(conversations),
        "chat_messages_deleted": int(messages),
        "password_resets_deleted": int(resets),
        "email_verifications_deleted": int(verifications),
        "used_invites_deleted": int(invites),
        "analytics_events_deleted": int(analytics_events),
        "answer_log_deleted": int(answer_log),
        "ai_usage_deleted": int(ai_usage),
        "ai_jobs_deleted": int(ai_jobs),
    }


def run_retention_sweep(
    db: Session, *, settings: Any, dry_run: bool = False, now: datetime | None = None
) -> dict[str, Any]:
    """Execute (or simulate) the retention sweep. Returns the counts report.

    dry_run=True performs NO deletes and commits NOTHING -- it is safe to
    call against production for compliance evidence.
    """
    if now is None:
        now = datetime.now(UTC).replace(tzinfo=None)
    analytics_days = getattr(settings, "analytics_retention_days", None)
    answer_days = getattr(settings, "answer_log_retention_days", None)
    usage_days = getattr(settings, "ai_usage_retention_days", None)
    jobs_days = getattr(settings, "ai_jobs_retention_days", None)
    report = retention_report(
        db,
        now=now,
        chat_retention_days=settings.chat_retention_days,
        analytics_retention_days=analytics_days,
        answer_log_retention_days=answer_days,
        ai_usage_retention_days=usage_days,
        ai_jobs_retention_days=jobs_days,
    )
    if dry_run:
        return {"dry_run": True, **report}

    chat_cutoff = now - timedelta(days=settings.chat_retention_days)
    token_cutoff = now - timedelta(days=TOKEN_GRACE_DAYS)
    analytics_cutoff = now - timedelta(
        days=settings.chat_retention_days if analytics_days is None else analytics_days
    )
    answer_cutoff = now - timedelta(days=730 if answer_days is None else answer_days)
    usage_cutoff = now - timedelta(days=365 if usage_days is None else usage_days)
    jobs_cutoff = now - timedelta(days=30 if jobs_days is None else jobs_days)

    _sweep_chat(db, cutoff=chat_cutoff)
    _delete_ranked(db, PasswordReset, PasswordReset.id, PasswordReset.expires_at < token_cutoff)
    _delete_ranked(
        db,
        EmailVerification,
        EmailVerification.id,
        EmailVerification.expires_at < token_cutoff,
    )
    _delete_ranked(
        db,
        ParentInvite,
        ParentInvite.id,
        (ParentInvite.expires_at < token_cutoff) & (ParentInvite.used_at.isnot(None)),
    )
    _delete_ranked(
        db,
        AnalyticsEventRow,
        AnalyticsEventRow.id,
        AnalyticsEventRow.created_at < analytics_cutoff,
    )
    _delete_ranked(
        db,
        AnswerLog,
        AnswerLog.id,
        AnswerLog.created_at < answer_cutoff,
    )
    _delete_ranked(
        db,
        AiUsage,
        AiUsage.id,
        AiUsage.created_at < usage_cutoff,
    )
    # F-007: ai_jobs has a UUID primary key, so the id-cursor helper above
    # does not apply; expired rows are removed in bounded id batches.
    _delete_by_id_batches(
        db,
        AiJob,
        AiJob.id,
        (AiJob.status.in_(TERMINAL_STATUSES)) & (AiJob.updated_at < jobs_cutoff),
    )
    # The pre-delete retention_report counts ARE the report (dialect-safe;
    # bulk-delete rowcount varies across drivers).
    return {"dry_run": False, **report}


def _sweep_chat(db: Session, *, cutoff: datetime, chunk_size: int = DELETE_CHUNK) -> None:
    """Age chat rows by their own timestamps, then drop the emptied threads.

    DAT-001: messages go first and on ``chat_messages.created_at``; the
    conversation row follows only once it has nothing inside the window left
    (``_expired_conversation_where``), so no row whose own timestamp is inside
    the window is ever deleted and no emptied conversation is left orphaned.

    DAT-002: both deletes walk ids one chunk at a time -- ``_delete_ranked``'s
    keyset cursor for the ids, and a per-chunk feedback detach -- so no single
    statement binds more than ``chunk_size`` variables and neither the SQLite
    (32766) nor the Postgres (65535) ceiling can wedge a run that is retried
    identically.
    """
    _delete_ranked(
        db,
        ChatMessage,
        ChatMessage.id,
        _expired_message_where(cutoff),
        chunk_size=chunk_size,
        # Clear feedback pointers inside the same chunk, BEFORE the delete:
        # feedback.message_id is a nullable FK into chat_messages, so deleting
        # the rows directly is the same ForeignKeyViolation that broke account
        # erasure (F-093). Per chunk, the pointer never outlives its message
        # even if the sweep dies between chunks.
        before_delete=lambda batch: _detach_feedback_from_messages(db, batch),
    )
    _delete_ranked(
        db,
        Conversation,
        Conversation.id,
        _expired_conversation_where(cutoff),
        chunk_size=chunk_size,
    )


def _delete_ranked(
    db: Session,
    model: type,
    id_col: Any,
    where: Any,
    *,
    chunk_size: int = DELETE_CHUNK,
    before_delete: Callable[[list[int]], None] | None = None,
) -> None:
    """Delete matching rows in bounded chunks, one commit per chunk (DB-03).

    Selection walks the table by primary-key cursor (``id > last_id ORDER
    BY id LIMIT chunk``), so each batch is an index seek + a small IN
    delete instead of one unbounded transaction. The caller's surrounding
    transaction is committed as part of each chunk: a mid-sweep crash
    leaves only completed chunks behind, which a pure-DELETE sweep treats
    exactly the same on the next run (expired-only, idempotent).

    ``before_delete`` runs on the batch read for this chunk, before its
    DELETE and its commit (DAT-001: the feedback detach must be part of the
    same unit, so no committed state has a pointer at a row that is gone).
    """
    last_id = 0
    while True:
        ids = (
            db.execute(
                select(id_col).where(where, id_col > last_id).order_by(id_col).limit(chunk_size)
            )
            .scalars()
            .all()
        )
        if not ids:
            break
        last_id = int(ids[-1])
        if before_delete is not None:
            before_delete(list(ids))
        db.execute(delete(model).where(id_col.in_(ids)))
        db.commit()


def _delete_by_id_batches(
    db: Session,
    model: type,
    id_col: Any,
    where: Any,
    *,
    chunk_size: int = DELETE_CHUNK,
) -> None:
    """Delete matching rows in bounded id batches, one commit per batch.

    Used for tables whose primary key is not an ascending integer
    (``ai_jobs.id`` is a random UUID string), where the keyset cursor of
    :func:`_delete_ranked` cannot order rows. Each pass deletes the batch it
    read, so the next SELECT sees strictly fewer expired rows and the loop
    terminates; a crash mid-sweep leaves completed batches behind and the
    next run continues (expired-only, idempotent).
    """
    while True:
        ids = db.execute(select(id_col).where(where).limit(chunk_size)).scalars().all()
        if not ids:
            break
        db.execute(delete(model).where(id_col.in_(ids)))
        db.commit()


def _detach_feedback_from_messages(db: Session, message_ids: Sequence[int]) -> None:
    """Null the nullable feedback FKs pointing at soon-to-be-deleted messages.

    The feedback row itself is product history and is kept; only the pointer
    into the erased conversation is dropped, which is the same policy the
    account-erasure path uses for AuditLog.actor_user_id and
    ChapterContent.created_by.

    Called once per message chunk (DAT-002), with the batch ``_delete_ranked``
    has just read: the UPDATE binds the same bounded set as the DELETE that
    follows it, instead of every id of every expired conversation. The batch is
    never empty -- the caller breaks out of its loop on an empty read before
    invoking this.
    """
    # Imported here rather than at module scope: retention.py must stay
    # importable without dragging the whole model graph into a count-only path.
    from sqlalchemy import update

    from bangla_gpt_api.db.models import Feedback as _Feedback

    db.execute(
        update(_Feedback).where(_Feedback.message_id.in_(message_ids)).values(message_id=None)
    )
