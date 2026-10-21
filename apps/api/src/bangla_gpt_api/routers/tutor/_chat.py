"""Tutor routes, split by surface (C-03): the single-shot ask, the
conversation history, the streamed chat, feedback, and product events.

_chat — C-03 split of ``routers/tutor.py``: same paths, same order, same
guards as the single module it came from.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    ChatMessage,
)
from bangla_gpt_api.providers import (
    ProviderError,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import (
    AskResponse,
    ChatMessageOut,
    ChatSendRequest,
)
from bangla_gpt_api.services import teach_strategy as teach
from bangla_gpt_api.services.activity import (
    record_activity,
)
from bangla_gpt_api.services.costs import (
    check_ai_budget,
    check_conversation_cap,
    check_daily_cost_breaker,
    check_school_daily_budget,
    record_ai_usage,
)
from bangla_gpt_api.services.tutor import VISION_UNSUPPORTED_ANSWER

from .._image_contract import _validate_chat_image
from ..common import (
    _answer_confidence,
    _request_context,
    _student_profile,
    canonical_subject,
    source_scores,
)
from ..deps import (
    Ctx,
    CurrentUser,
    DbSession,
    _provider_lacks_vision,
)
from ._ask import (  # noqa: F401
    ask as ask,
)
from ._shared import (  # noqa: F401
    DEFAULT_INFLIGHT_CHAT as DEFAULT_INFLIGHT_CHAT,
)
from ._shared import (
    SSE_STREAM_HEADERS as SSE_STREAM_HEADERS,
)
from ._shared import (
    _held_stream_slot as _held_stream_slot,
)
from ._shared import (
    _inflight_slot as _inflight_slot,
)
from ._shared import (
    _own_conversation as _own_conversation,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)


def _chat_history(app_ctx: Ctx, db: Session, conversation_id: int) -> list[dict[str, str]]:
    rows = (
        db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.id.desc())
            .limit(app_ctx.settings.chat_history_messages)
        )
        .scalars()
        .all()
    )
    # A24: history replay is count-limited AND char-limited per message, so
    # one giant pasted turn cannot blow the prompt context budget.
    limit = app_ctx.settings.chat_history_message_char_limit
    history = [{"role": m.role, "content": m.content[:limit]} for m in reversed(rows)]
    return history


@router.post("/tutor/conversations/{conversation_id}/messages", response_model=ChatMessageOut)
async def send_chat_message(
    app_ctx: Ctx, conversation_id: int, payload: ChatSendRequest, db: DbSession, user: CurrentUser
) -> ChatMessageOut:
    """Non-streaming chat turn: persists both sides and returns the reply."""
    tutor = app_ctx.tutor
    if tutor is None:
        raise HTTPException(status_code=503, detail="Tutor service unavailable")
    # AI-002: budget gate before spending upstream tokens.
    check_ai_budget(db, user_id=user.id, settings=app_ctx.settings)
    # A7-05: platform and school daily breakers, then the conversation cap
    # (extra_messages=1 counts the turn being written).
    check_daily_cost_breaker(db, settings=app_ctx.settings)
    check_school_daily_budget(db, school_id=user.school_id, settings=app_ctx.settings)
    conv = _own_conversation(db, conversation_id, user)
    check_conversation_cap(db, conversation_id=conv.id, settings=app_ctx.settings, extra_messages=1)
    student = _student_profile(db, user)
    class_level = payload.class_level or student.class_level or 6
    history = _chat_history(app_ctx, db, conv.id)
    # vision contract: validated BEFORE anything is persisted.
    image_payload = _validate_chat_image(payload.image)

    # 'আমি বুঝিন': swap to the next explanation strategy and remember it.
    # an explicit strategy request OVERRIDES the rotation and is
    # persisted as last_strategy so the next turn keeps learning from it.
    extra_instruction: str | None = None
    goal = "chat"
    if payload.strategy:
        extra_instruction = teach.explicit_strategy_instruction(payload.strategy)
        conv.last_strategy = payload.strategy
    elif payload.reteach:
        strategy_key, extra_instruction = teach.reteach_instruction(conv.last_strategy)
        conv.last_strategy = strategy_key
        goal = "reteach"

    user_msg = ChatMessage(conversation_id=conv.id, role="user", content=payload.message)
    db.add(user_msg)
    # Flush (not commit): the user turn must not survive a failed LLM call,
    # otherwise the provider error leaves an orphan message behind.
    db.flush()

    if image_payload is not None and _provider_lacks_vision(app_ctx):
        # Honest refusal: the mock provider cannot see images at all.
        result = AskResponse(
            answer=VISION_UNSUPPORTED_ANSWER,
            grounded=False,
            sources=[],
            refused_reason="vision_unsupported",
        )
    else:
        try:
            with _inflight_slot(app_ctx, user, default=DEFAULT_INFLIGHT_CHAT):
                result = await tutor.ask(
                    payload.message,
                    class_level,
                    canonical_subject(payload.subject),
                    history,
                    chapter=payload.chapter,
                    extra_instruction=extra_instruction,
                    low_data=payload.low_data,
                    context=_request_context(
                        db,
                        user,
                        class_level=class_level,
                        subject=canonical_subject(payload.subject),
                        chapter=payload.chapter,
                        goal=goal,
                        history=history,
                        strategy=conv.last_strategy,
                    ),
                    image=image_payload,
                )
        except ProviderError as exc:
            db.rollback()
            raise HTTPException(
                status_code=502,
                detail={"code": "llm_unavailable", "message": "LLM provider unavailable"},
            ) from exc

    assistant_msg = ChatMessage(
        conversation_id=conv.id,
        role="assistant",
        content=result.answer,
        grounded=result.grounded,
        refused_reason=result.refused_reason,
        sources_json=[s.model_dump() for s in result.sources],
    )
    db.add(assistant_msg)
    if conv.title is None:
        conv.title = payload.message[:80]
    # AI-002: ledger the generation (vision refusals never reach a provider).
    if image_payload is None or not _provider_lacks_vision(app_ctx):
        record_ai_usage(
            db,
            user_id=user.id,
            route="tutor.chat",
            model=getattr(tutor.provider, "model", None) or tutor.provider.name,
            prompt_text=payload.message,
            answer_text=result.answer,
        )
    db.commit()
    # one question ≈ one minute of study for the daily counters.
    record_activity(db, conv.student_id, questions=1, minutes=1)
    return ChatMessageOut(
        id=assistant_msg.id,
        role=assistant_msg.role,
        content=assistant_msg.content,
        grounded=assistant_msg.grounded,
        refused_reason=assistant_msg.refused_reason,
        sources=result.sources,
        confidence=_answer_confidence(
            assistant_msg.grounded, assistant_msg.refused_reason, source_scores(result.sources)
        ),
        rating=None,
        created_at=assistant_msg.created_at,
    )


@router.post("/tutor/conversations/{conversation_id}/messages/stream")
async def stream_chat_message(
    app_ctx: Ctx, conversation_id: int, payload: ChatSendRequest, db: DbSession, user: CurrentUser
) -> StreamingResponse:
    """SSE streaming chat turn: token events, then one final JSON event."""
    tutor = app_ctx.tutor
    if tutor is None:
        raise HTTPException(status_code=503, detail="Tutor service unavailable")
    # AI-002: budget gate before spending upstream tokens.
    check_ai_budget(db, user_id=user.id, settings=app_ctx.settings)
    # A7-05: same breaker set as the non-stream chat route.
    check_daily_cost_breaker(db, settings=app_ctx.settings)
    check_school_daily_budget(db, school_id=user.school_id, settings=app_ctx.settings)
    conv = _own_conversation(db, conversation_id, user)
    check_conversation_cap(db, conversation_id=conv.id, settings=app_ctx.settings, extra_messages=1)
    # Read-only preparation and input validation run BEFORE the in-flight slot
    # is taken: a turn refused for a bad image (422) or an unknown conversation
    # (404) must not consume concurrency capacity. Taking the slot first made
    # two rejected uploads hold the whole per-identity cap until the backend
    # TTL expired, so the next legitimate turn answered 429 (R3/WS5 regression
    # test: tests/test_r3_ws5_stream_slots.py).
    student = _student_profile(db, user)
    class_level = payload.class_level or student.class_level or 6
    history = _chat_history(app_ctx, db, conv.id)
    # vision contract: validated BEFORE anything is persisted.
    image_payload = _validate_chat_image(payload.image)

    # 'আমি বুঝিন': swap to the next explanation strategy and remember it.
    # explicit strategy OVERRIDES the rotation (persisted likewise).
    extra_instruction: str | None = None
    goal = "chat"
    if payload.strategy:
        extra_instruction = teach.explicit_strategy_instruction(payload.strategy)
        conv.last_strategy = payload.strategy
    elif payload.reteach:
        strategy_key, extra_instruction = teach.reteach_instruction(conv.last_strategy)
        conv.last_strategy = strategy_key
        goal = "reteach"

    # build the context before streaming so the log line lands once.
    ctx = _request_context(
        db,
        user,
        class_level=class_level,
        subject=canonical_subject(payload.subject),
        chapter=payload.chapter,
        goal=goal,
        history=history,
        strategy=conv.last_strategy,
    )
    no_vision = image_payload is not None and _provider_lacks_vision(app_ctx)

    # A7-05 in-flight cap: taken BEFORE the response starts (a refusal here is
    # still an HTTP 429); released in event_stream's finally, which runs on
    # client disconnect too.
    stream_limiter, stream_slot_key, _stream_limit = _held_stream_slot(
        app_ctx, user, default=DEFAULT_INFLIGHT_CHAT
    )
    # Everything between the acquire above and the StreamingResponse below runs
    # with the slot held but WITHOUT the generator that normally releases it, so
    # a failure here (a write error on the user turn) would leak the slot for
    # the whole backend TTL. The guard releases it and lets the error surface;
    # on the success path the generator owns the slot and releases it exactly
    # once in its finally.
    try:
        user_msg = ChatMessage(conversation_id=conv.id, role="user", content=payload.message)
        db.add(user_msg)
        # commit before streaming to release DB session/connection during LLM stream
        # (was flush-only, holding transaction for up to 30s). User turn is persisted alone;
        # assistant turn will be persisted in a short second transaction after stream.
        db.commit()
        db.refresh(user_msg)
    except BaseException:
        if stream_limiter is not None:
            stream_limiter.release(stream_slot_key)
        raise

    async def event_stream() -> AsyncIterator[str]:
        try:
            final_response: AskResponse | None = None
            if no_vision:
                # Honest refusal: the mock provider cannot see images at
                # all -- emitted as one token + the normal done event.
                final_response = AskResponse(
                    answer=VISION_UNSUPPORTED_ANSWER,
                    grounded=False,
                    sources=[],
                    refused_reason="vision_unsupported",
                )
                token_payload = json.dumps({"text": VISION_UNSUPPORTED_ANSWER}, ensure_ascii=False)
                yield f"event: token\ndata: {token_payload}\n\n"
            else:
                async for event in tutor.ask_stream(
                    payload.message,
                    class_level,
                    canonical_subject(payload.subject),
                    history,
                    chapter=payload.chapter,
                    extra_instruction=extra_instruction,
                    low_data=payload.low_data,
                    context=ctx,
                    image=image_payload,
                ):
                    if event.type == "token":
                        token_payload = json.dumps({"text": event.text}, ensure_ascii=False)
                        yield f"event: token\ndata: {token_payload}\n\n"
                    elif event.type == "citation":
                        # A6-08: validated sources before the final event, so
                        # a client renders citations without waiting for done.
                        yield (
                            "event: citation\ndata: "
                            + json.dumps(event.extra, ensure_ascii=False)
                            + "\n\n"
                        )
                    elif event.type == "heartbeat":
                        # A6-08: liveness while the provider is silent.
                        yield (
                            "event: heartbeat\ndata: "
                            + json.dumps(event.extra, ensure_ascii=False)
                            + "\n\n"
                        )
                    elif event.type == "error":
                        # A6-08: mid-stream failure; the final event (if any)
                        # still carries the honest replacement answer.
                        yield (
                            "event: error\ndata: "
                            + json.dumps(event.extra, ensure_ascii=False)
                            + "\n\n"
                        )
                    elif event.response is not None:
                        final_response = event.response
            if final_response is None:  # never leak a naked 500 under -O
                # user_msg already committed before stream; no rollback needed
                yield (
                    "event: error\ndata: "
                    + json.dumps({"code": "llm_unavailable"}, ensure_ascii=False)
                    + "\n\n"
                )
                return
            assistant_msg = ChatMessage(
                conversation_id=conv.id,
                role="assistant",
                content=final_response.answer,
                grounded=final_response.grounded,
                refused_reason=final_response.refused_reason,
                sources_json=[s.model_dump() for s in final_response.sources],
            )
            db.add(assistant_msg)
            if conv.title is None:
                conv.title = payload.message[:80]
            # AI-002: ledger the generation (mock-vision refusals cost nothing).
            if not no_vision:
                record_ai_usage(
                    db,
                    user_id=user.id,
                    route="tutor.chat.stream",
                    model=getattr(tutor.provider, "model", None) or tutor.provider.name,
                    prompt_text=payload.message,
                    answer_text=final_response.answer,
                )
            db.commit()
            record_activity(db, conv.student_id, questions=1, minutes=1)
            done_payload = {
                "user_message_id": user_msg.id,
                "message_id": assistant_msg.id,
                **final_response.model_dump(),
                # additive grounding-confidence in [0,1] (see
                # _answer_confidence for the documented formula).
                "confidence": _answer_confidence(
                    final_response.grounded,
                    final_response.refused_reason,
                    source_scores(final_response.sources),
                ),
            }
            yield ("event: done\ndata: " + json.dumps(done_payload, ensure_ascii=False) + "\n\n")
        except ProviderError:
            # user turn already persisted; do not rollback
            with contextlib.suppress(Exception):  # rollback is best-effort here
                db.rollback()
            yield (
                "event: error\ndata: "
                + json.dumps({"code": "llm_unavailable"}, ensure_ascii=False)
                + "\n\n"
            )
        finally:
            # A7-05: the in-flight slot spans the whole stream and is released
            # on completion, failure and client disconnect alike.
            if stream_limiter is not None:
                stream_limiter.release(stream_slot_key)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_STREAM_HEADERS,
    )
