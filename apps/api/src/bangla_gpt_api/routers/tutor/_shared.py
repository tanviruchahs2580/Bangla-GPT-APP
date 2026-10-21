"""Tutor routes, split by surface (C-03): the single-shot ask, the
conversation history, the streamed chat, feedback, and product events.

_shared — C-03 split of ``routers/tutor.py``: same paths, same order, same
guards as the single module it came from.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    Conversation,
    Student,
    User,
)
from bangla_gpt_api.ratelimit import (
    ConcurrencyLimitExceeded,
    build_concurrency_limiter,
    concurrency_slot,
)

from ..deps import (
    Ctx,
)

logger = logging.getLogger(__name__)

INFLIGHT_ENV_KEY = "AI_MAX_INFLIGHT_PER_USER"


DEFAULT_INFLIGHT_CHAT = 2


DEFAULT_INFLIGHT_SINGLE = 1


def _inflight_limit(settings: Any, *, default: int) -> int:
    """Resolve the per-identity in-flight cap: settings field, env, default."""
    raw = getattr(settings, "ai_max_inflight_per_user", None)
    if raw is None:
        raw = os.environ.get(INFLIGHT_ENV_KEY)
    if raw is None or raw == "":
        return default
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        logger.warning("invalid %s=%r; using %d", INFLIGHT_ENV_KEY, raw, default)
        return default


def _concurrency_limiter(app_ctx: Ctx) -> Any:
    """Per-app in-flight limiter, built once on the rate-limit backend.

    Built lazily and stored on the app context so every route (and every test
    app instance) shares exactly one limiter -- the shared state is the cap.
    """
    limiter = getattr(app_ctx, "concurrency_limiter", None)
    if limiter is None:
        limiter = build_concurrency_limiter(app_ctx.settings)
        app_ctx.concurrency_limiter = limiter
    return limiter


def _inflight_key(user: User) -> str:
    return f"user:{user.id}"


def _concurrency_refusal() -> HTTPException:
    """429 for a saturated in-flight cap (declared 429 body: code rate_limited).

    A distinct code (too_many_concurrent_requests) would need a new row in the
    error catalog (routers/_error_contract.ERROR_CATALOG), which is owned by
    another workstream; the message plus Retry-After carry the distinction
    until that row lands.
    """
    return HTTPException(
        status_code=429,
        detail={
            "code": "rate_limited",
            "message": "Too many AI requests in flight for this account; retry shortly.",
        },
        headers={"Retry-After": "2"},
    )


def effective_inflight_limit(settings: Any, role: str, *, default: int) -> int:
    """A7-05: the per-role in-flight cap for one account.

    Higher-privilege roles can be narrowed below the base cap (their turn
    costs more), via TEACHER_INFLIGHT_CAP / ADMIN_INFLIGHT_CAP; 0 inherits the
    base. The base itself resolves through _inflight_limit, so disabling the
    base cap disables the role cap too.
    """
    limit = _inflight_limit(settings, default=default)
    role_cap = {
        "teacher": getattr(settings, "teacher_inflight_cap", 0) or 0,
        "admin": getattr(settings, "admin_inflight_cap", 0) or 0,
    }.get(role, 0)
    if role_cap <= 0 or limit <= 0:
        return limit
    return min(limit, role_cap)


@contextmanager
def _inflight_slot(app_ctx: Ctx, user: User, *, default: int) -> Iterator[None]:
    """Hold one in-flight slot around a generation call (A7-05).

    The slot is released in a ``finally`` (concurrency_slot's contract), so a
    failed or cancelled turn cannot leak capacity.
    """
    limit = effective_inflight_limit(app_ctx.settings, user.role, default=default)
    if limit <= 0:
        yield
        return
    try:
        with concurrency_slot(_concurrency_limiter(app_ctx), _inflight_key(user), limit):
            yield
    except ConcurrencyLimitExceeded as exc:
        raise _concurrency_refusal() from exc


def _held_stream_slot(app_ctx: Ctx, user: User, *, default: int) -> tuple[Any, str, int]:
    """Take one in-flight slot FOR A STREAM and return the release triple.

    A streaming response has already started by the time generation begins, so
    the slot is taken before the StreamingResponse is returned (a refusal here
    is still a normal 429) and the caller releases it in the event stream's
    ``finally`` -- which runs on client disconnect too.
    """
    limit = _inflight_limit(app_ctx.settings, default=default)
    if limit <= 0:
        return None, "", 0
    limiter = _concurrency_limiter(app_ctx)
    key = _inflight_key(user)
    if not limiter.acquire(key, limit):
        raise _concurrency_refusal()
    return limiter, key, limit


def _own_conversation(db: Session, conversation_id: int, user: User) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "conversation_not_found", "message": "Conversation not found"},
        )
    owner = db.execute(select(Student).where(Student.id == conv.student_id)).scalar_one_or_none()
    if owner is None or owner.user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "not_allowed",
                "message": "Not allowed to access this conversation",
            },
        )
    return conv


SSE_STREAM_HEADERS: dict[str, str] = {
    "X-Accel-Buffering": "no",
    "Cache-Control": "no-cache, no-transform",
}
