"""Cheap, side-effect-free signals: heartbeat timing, the hint-first switch,
homework detection, image-payload sanitisation and the safety screen.

signals — C-03 split of ``services/tutor.py``: moved verbatim.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from bangla_gpt_api.services.answer_structure import (  # noqa: F401 (re-export for prompt/mock/tests)
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
    SHORT_ANSWER_INSTRUCTION,
)
from bangla_gpt_api.services.prompt_registry import (  # noqa: F401 (re-export)
    PROMPTS_DIR_ENV,
    PromptSpec,
    load_prompt,
    prompts_dir,
)
from bangla_gpt_api.services.safety import (
    refusal_for,
    screen_question,
)
from bangla_gpt_api.services.safety import (
    render_image_text_block as render_image_text_block,
)
from bangla_gpt_api.services.safety import (
    sanitize_evidence as sanitize_evidence,
)
from bangla_gpt_api.services.safety import (
    sanitize_image_text as sanitize_image_text,
)
from bangla_gpt_api.services.tutor.prompts import (  # noqa: F401
    _MODEL_REFUSAL_MARKER,
)

logger = logging.getLogger("bangla_gpt_api.tutor")

# --- streaming contract (A6-08 / AUD-A2-16) --------------------------------
#
# Documented here because it is the contract every SSE client depends on.
# The transport framing (``event: <type>\ndata: <json>\n\n``) lives in
# routers/tutor.py; this constant is the semantic half.
#
# Event schema
#   token     data {"text": <str>}          -- one answer delta, in order.
#   citation  data {"sources": [...], "citation_verified": true} -- emitted
#             once, after the tokens, ONLY when the answer passed the
#             post-generation grounding check. Carries the validated source
#             list so a client can render citations before the final event.
#   heartbeat data {"interval_seconds": <num>} -- emitted when no token has
#             been produced for STREAM_HEARTBEAT_SECONDS. Proves to the
#             client (and to any proxy) that the stream is alive through a
#             slow provider; carries no answer content.
#   error     data {"code": <str>, "recoverable": <bool>} -- emitted when the
#             stream fails after it has started. Tokens already sent stay on
#             screen; the following final event carries the honest
#             replacement (degraded passages or the outage notice).
#   final     data = the complete AskResponse (+ counts). Exactly one per
#             turn, always last. Its ``answer`` SUPERSEDES everything
#             streamed before it, because the grounding check runs only once
#             the full answer exists.
#
# Mid-stream error policy: a provider failure after the first token is never
# retried on the same stream (a truncated answer cannot be spliced); the
# client receives ``error`` plus one ``final`` event, and the persisted
# assistant turn is the final event's answer only.
#
# Reconnection policy: the user turn is persisted BEFORE streaming starts, so
# a client that reconnects must NOT resend it; it should GET the conversation
# messages and, if the last user turn has no assistant reply, request a fresh
# stream for the same turn. A reconnect never resumes a half-written answer:
# partial-answer persistence semantics are "the assistant turn is saved only
# from the final event", so a dropped stream leaves no partial row.
STREAM_HEARTBEAT_SECONDS = 10.0


STREAM_HEARTBEAT_ENV = "TUTOR_STREAM_HEARTBEAT_SECONDS"


STREAM_EVENT_TYPES = frozenset({"token", "citation", "heartbeat", "error", "final"})


def stream_heartbeat_seconds(settings: object | None = None) -> float:
    """Resolve the heartbeat interval: settings field, then env, then default.

    Interim plumbing until the settings field lands (handoff: api-rag2.md);
    the env override also lets tests shrink the interval without patching.
    """
    raw = (
        getattr(settings, "tutor_stream_heartbeat_seconds", None) if settings is not None else None
    )
    if raw is None:
        raw = os.environ.get(STREAM_HEARTBEAT_ENV)
    if raw is None:
        return STREAM_HEARTBEAT_SECONDS
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("invalid %s=%r; using default", STREAM_HEARTBEAT_ENV, raw)
        return STREAM_HEARTBEAT_SECONDS


#: Interim switch for hint-first behaviour until the settings field lands
#: (handoff: api-rag2.md). Truthy default: the pedagogy requirement is
#: hint-first for homework-like prompts; operators turn it off with
#: TUTOR_HINT_FIRST=0 (or the settings field once wired).
HINT_FIRST_ENV = "TUTOR_HINT_FIRST"


_FALSEY = frozenset({"0", "false", "no", "off", "disabled"})


#: Homework-like phrasing that triggers hint-first behaviour: "did my
#: homework", "solve it for me", "মূল্যায়ন করা হবে" style phrasing where a
#: student pastes an assignment. Deliberately conservative -- a normal
#: curriculum question ("সালোকসংশ্লেষণ কী?") must NOT be hint-gated.
_HOMEWORK_CUES = (
    r"হোমওয়ার্ক",
    r"হোম\s*ওয়ার্ক",
    r"বাড়ির\s*কাজ",
    r"বাসার\s*কাজ",
    r"অ্যাসাইনমেন্ট",
    r"assignment",
    r"home\s*-?\s*work",
    r"সমাধান\s*করে\s*দাও",
    r"উত্তর\s*লিখে\s*দাও",
    r"solve\s+(?:it\s+)?for\s+me",
)


_HOMEWORK_CUE_RE = re.compile("|".join(_HOMEWORK_CUES), re.IGNORECASE)


def hint_first_enabled(settings: object | None = None, *, default: bool = True) -> bool:
    """Resolve the hint-first flag: settings field, then env, then default."""
    raw = getattr(settings, "tutor_hint_first", None) if settings is not None else None
    if raw is None:
        raw = os.environ.get(HINT_FIRST_ENV)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in _FALSEY


def is_homework_like(question: str, history: list[dict[str, str]] | None = None) -> bool:
    """True when the question reads like a pasted assignment/homework.

    A11-03: a homework dialogue is not one turn. The student pastes the task,
    gets a hint, then replies "I tried" -- and that follow-up carries no cue
    of its own, which used to let the hint-first guardrail expire exactly when
    the model was about to be asked for the solution. The LAST user turn is
    therefore part of the test: while the conversation is inside the same
    homework exchange the guardrail stays. A fresh curriculum question becomes
    the new last turn and the guardrail ends by itself.
    """
    if _HOMEWORK_CUE_RE.search(question):
        return True
    for turn in reversed(history or []):
        if turn.get("role") == "user":
            return bool(_HOMEWORK_CUE_RE.search(str(turn.get("content", ""))))
    return False


def sanitize_image_payload(image: dict | None) -> tuple[dict | None, str | None]:
    """Second-pass image hygiene before the bytes reach a provider (A6-09).

    Returns ``(payload, refusal_reason)``: ``(None, None)`` for text-only
    turns, ``(payload, None)`` with metadata-free, quality-checked bytes, or
    ``(None, "image_unreadable")`` when the picture cannot be read honestly.
    The route-level validation already ran; this pass strips EXIF/PNG text
    chunks/trailing bytes (re-encode) and refuses blank, blurry or tiny
    images, so the model never guesses at a picture nobody can read.
    """
    if image is None:
        return None, None
    from bangla_gpt_api.providers.image_safety import ImageSanitizeError, sanitize_inline_image

    try:
        sanitized = sanitize_inline_image(image.get("mime_type", ""), image.get("data", ""))
    except ImageSanitizeError as exc:
        # the reason is structural (size/blur/decode), never image content
        logger.warning("chat_image_rejected: %s", exc)
        return None, "image_unreadable"
    return {"mime_type": sanitized.mime_type, "data": sanitized.base64()}, None


def _model_refused(answer: str) -> bool:
    return _MODEL_REFUSAL_MARKER in answer


@asynccontextmanager
async def _null_ctx() -> AsyncIterator[None]:
    """Async context manager that does nothing — for optional circuit breaker."""
    yield


def _screen_safety(question: str) -> tuple[str, str] | None:
    """Return (refusal_copy, reason) when the question violates safety rules."""
    verdict = screen_question(question)
    if not verdict.safe:
        reason = verdict.reason or "unsafe_content"
        return refusal_for(reason), reason
    return None
