"""S5.8 -- Retention policy job (shared core).

Single implementation used by BOTH:
* POST /admin/maintenance/purge (admin-triggered; dry_run=true = report-only
  for compliance evidence, dry_run=false = sweep + audit), and
* the nightly arq job (jobs.run_retention_sweep -> cron in worker.py).

Everything is counts-only (R11): the report and the audit row may say HOW
MANY rows expired, never what they contained.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    ChatMessage,
    Conversation,
    EmailVerification,
    ParentInvite,
    PasswordReset,
)

# Token/verification/invite rows keep a 30-day grace window after expiry
# (audit/replay window); chat follows the configured retention days.
TOKEN_GRACE_DAYS = 30


def retention_report(db: Session, *, now: datetime, chat_retention_days: int) -> dict[str, int]:
    """Counts of rows the sweep WOULD delete (no writes)."""
    chat_cutoff = now - timedelta(days=chat_retention_days)
    token_cutoff = now - timedelta(days=TOKEN_GRACE_DAYS)

    conversations = db.execute(
        select(func.count(Conversation.id)).where(Conversation.created_at < chat_cutoff)
    ).scalar_one()
    old_conv_ids = select(Conversation.id).where(Conversation.created_at < chat_cutoff)
    messages = db.execute(
        select(func.count(ChatMessage.id)).where(ChatMessage.conversation_id.in_(old_conv_ids))
    ).scalar_one()
    resets = db.execute(
        select(func.count(PasswordReset.id)).where(PasswordReset.expires_at < token_cutoff)
    ).scalar_one()
    verifications = db.execute(
        select(func.count(EmailVerification.id)).where(
            EmailVerification.expires_at < token_cutoff
        )
    ).scalar_one()
    invites = db.execute(
        select(func.count(ParentInvite.id)).where(
            ParentInvite.expires_at < token_cutoff,
            ParentInvite.used_at.isnot(None),
        )
    ).scalar_one()
    return {
        "conversations_deleted": int(conversations),
        "chat_messages_deleted": int(messages),
        "password_resets_deleted": int(resets),
        "email_verifications_deleted": int(verifications),
        "used_invites_deleted": int(invites),
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
    report = retention_report(
        db, now=now, chat_retention_days=settings.chat_retention_days
    )
    if dry_run:
        return {"dry_run": True, **report}

    chat_cutoff = now - timedelta(days=settings.chat_retention_days)
    token_cutoff = now - timedelta(days=TOKEN_GRACE_DAYS)
    old_convs = (
        db.execute(select(Conversation.id).where(Conversation.created_at < chat_cutoff))
        .scalars()
        .all()
    )
    if old_convs:
        db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(old_convs)))
        db.execute(delete(Conversation).where(Conversation.id.in_(old_convs)))
    db.execute(delete(PasswordReset).where(PasswordReset.expires_at < token_cutoff))
    db.execute(delete(EmailVerification).where(EmailVerification.expires_at < token_cutoff))
    db.execute(
        delete(ParentInvite).where(
            ParentInvite.expires_at < token_cutoff,
            ParentInvite.used_at.isnot(None),
        )
    )
    # The pre-delete retention_report counts ARE the report (dialect-safe;
    # bulk-delete rowcount varies across drivers).
    return {"dry_run": False, **report}
