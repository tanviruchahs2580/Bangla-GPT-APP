"""SQLAlchemy models: platform (split out of db/models.py, C-03)."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models.base import (  # noqa: F401
    _utcnow as _utcnow,
)
from bangla_gpt_api.db.types import UtcDateTime


class Conversation(Base):
    """A multi-turn tutoring chat owned by exactly one student."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # last explanation strategy used in this conversation ('আমি বুঝিন' loop).
    last_strategy: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)

    messages: Mapped[list[ChatMessage]] = relationship(back_populates="conversation")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
        CheckConstraint("rating IS NULL OR rating IN (-1, 1)", name="ck_chat_messages_rating"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text)
    grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    refused_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sources_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # -1 | +1
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Feedback(Base):
    """Thumbs up/down product feedback on tutor answers."""

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("rating BETWEEN -1 AND 1", name="ck_feedback_rating"),
        CheckConstraint("triaged = false OR triaged_at IS NOT NULL", name="ck_feedback_triaged_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id"), nullable=True, index=True
    )
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("quiz_attempts.id"), nullable=True, index=True
    )
    # -1 = down, +1 = up, 0 = no verdict (comment-only feedback; the schema
    # keeps 0 valid because `rating` is required). Aggregates count -1/+1 only.
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # triage queue: admins work the queue oldest-first and mark rows
    # handled; triage_note is staff-facing text, still never chat/message logs.
    triaged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    triaged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    triage_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class JobRun(Base):
    """idempotency ledger for scheduled jobs.

    One row per (job, period_key) claimed, enforced by the composite primary
    key. Any number of web workers / ARQ workers can race the same schedule
    slot: exactly one INSERT wins, the rest skip. This is what makes jobs
    double-run safe across pods (replaces the old per-process in-memory
    "last run" state, which broke under gunicorn -w N).
    """

    __tablename__ = "job_runs"

    job: Mapped[str] = mapped_column(String(80), primary_key=True)
    period_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AnalyticsEventRow(Base):
    """persisted product analytics events (sanitized scalars only).

    ``user_id`` deliberately has NO FK: the trail is append-only privacy
    history cleaned by the retention sweep, so it must never block (or be
    blocked by) account deletion. Only sanitized scalar props live in
    ``props`` -- PII-looking keys are dropped before the row is written.
    """

    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    props: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, index=True)


class AiJob(Base):
    """async generation job (§37) with a linear status lifecycle.

    queued -> generating -> validating -> ready | failed. The job row is the
    single source of truth; the inline runner opens its own session so the
    request session is never reused.
    """

    __tablename__ = "ai_jobs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'generating', 'validating', 'ready', 'failed')",
            name="ck_ai_jobs_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, onupdate=_utcnow)


class AiUsage(Base):
    """AI-002: per-request LLM usage ledger (cost control foundation).

    One row per generation that reached a provider (ask/chat/stream/document
    jobs). Token counts are planning estimates (see services/costs.py), never
    vendor-metered values — good enough for budgets and dashboards, honest
    about precision. Cleaned by DELETE /users/me (BUG-4 rule).
    """

    __tablename__ = "ai_usage"

    __table_args__ = (
        CheckConstraint("prompt_tokens >= 0", name="ck_ai_usage_prompt_tokens"),
        CheckConstraint("completion_tokens >= 0", name="ck_ai_usage_completion_tokens"),
        CheckConstraint("estimated_cost_usd >= 0", name="ck_ai_usage_estimated_cost_usd"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    route: Mapped[str] = mapped_column(String(40), default="tutor.ask")
    model: Mapped[str] = mapped_column(String(80), default="mock")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, index=True)
