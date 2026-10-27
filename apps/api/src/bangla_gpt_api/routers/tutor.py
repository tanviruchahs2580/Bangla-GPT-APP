"""Tutor Routes — split from the main.py god-module.

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via:mod:`.deps`, shared helpers via:mod:`.common`.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, NamedTuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    AiUsage,
    AnalyticsEventRow,
    ChatMessage,
    Conversation,
    Feedback,
    QuizAttempt,
    Student,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.providers import (
    ProviderError,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES, coded
from bangla_gpt_api.schemas import (
    AnalyticsEvent,
    AskRequest,
    AskResponse,
    ChatMessageOut,
    ChatSendRequest,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    FeedbackAdminRow,
    FeedbackOut,
    FeedbackQueuePage,
    FeedbackRequest,
    MessageSearchHit,
    SourceRef,
    TriageUpdate,
)
from bangla_gpt_api.services import teach_strategy as teach
from bangla_gpt_api.services.activity import (
    record_activity,
)
from bangla_gpt_api.services.context import RequestContext
from bangla_gpt_api.services.costs import (
    check_ai_budget,
    finalize_ai_usage,
    reserve_ai_usage,
)
from bangla_gpt_api.services.quiz_explain import quiz_explain_instruction
from bangla_gpt_api.services.tutor import VISION_UNSUPPORTED_ANSWER, StreamEvent

from .common import (
    _answer_confidence,
    _request_context,
    _sanitize_event_props,
    _student_profile,
    _validate_chat_image,
    canonical_subject,
    source_scores,
)
from .deps import (
    AdminUser,
    Ctx,
    CurrentUser,
    DbSession,
    _provider_lacks_vision,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)

#: Idle seconds before the SSE stream emits a `: ping` comment line. Proxies
#: and load balancers commonly drop a silent connection at 30-60s; retrieval
#: plus provider time-to-first-token can legitimately exceed that.
SSE_HEARTBEAT_SECONDS = 15.0


def _ask_prepare(
    app_ctx: Ctx, db: Session, user: User, payload: AskRequest
) -> tuple[str | None, str, str | None, RequestContext, AiUsage]:
    """DB prelude to /tutor/ask: budget gate + reserve + education context."""
    # AI-002: budget gate before spending upstream tokens.
    check_ai_budget(db, user_id=user.id, settings=app_ctx.settings)
    explain_instruction = quiz_explain_instruction(payload.explain) if payload.explain else None
    # retrieve on the quiz topic itself — the generic
    # 'explain this' phrasing carries no subject keywords. the
    # phrasing is dropped from the RETRIEVE/gate query entirely (it
    # diluted coverage below the grounding gate); it stays in the
    # prompt so the model still sees the student's own words.
    question = payload.question
    search_query: str | None = None
    if payload.explain:
        question = f"{payload.question}\n{payload.explain.question}"
        search_query = payload.explain.question
    # every AI call carries the central education context.
    ctx = _request_context(
        db,
        user,
        class_level=payload.class_level,
        subject=canonical_subject(payload.subject),
        chapter=payload.chapter,
        goal="quiz_explain" if payload.explain else "question",
    )
    # BE-01: reserve the ledger row now (BEFORE the provider call) so the
    # budget gate of any concurrent generation counts this in-flight spend.
    # Committed in its own transaction: the row is only budget-visible once
    # it is durable. The route refuses a missing tutor before calling here;
    # the local guard keeps the type checker honest too.
    tutor = app_ctx.tutor
    if tutor is None:  # pragma: no cover - route-level 503 precedes this
        raise HTTPException(
            status_code=503,
            detail={"code": "tutor_unavailable", "message": "Tutor service unavailable"},
        )
    model = getattr(tutor.provider, "model", None) or tutor.provider.name
    pending = reserve_ai_usage(
        db,
        user_id=user.id,
        route="tutor.ask",
        model=model,
        prompt_text=question,
    )
    db.commit()
    return explain_instruction, question, search_query, ctx, pending


def _ask_ledger(
    db: Session,
    user: User,
    *,
    question: str,
    answer: str | None,
    model: str,
    pending: AiUsage | None = None,
) -> None:
    """DB postlude to /tutor/ask: finalize the reserved ledger row (or
    append, legacy shape), activity counters, commit. ``answer=None`` is
    the provider-failure path: the prompt-side spend is real and stays
    ledgered at zero completion tokens."""
    # BE-01: the reserve, finalized in place — one row per generation, with
    # the answer the provider actually produced (a refusal answer included:
    # it went through the model's safety path, and its tokens were real).
    finalize_ai_usage(db, pending, model=model, answer_text=answer)
    # one tutoring question ≈ one minute of study for the daily
    # counters (the chat routes already record; ask must not be a gap).
    if user.role == "student":
        record_activity(db, _student_profile(db, user).id, questions=1, minutes=1)
    db.commit()


@router.post("/tutor/ask", response_model=AskResponse)
async def ask(app_ctx: Ctx, payload: AskRequest, db: DbSession, user: CurrentUser) -> AskResponse:
    tutor = app_ctx.tutor
    if tutor is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "tutor_unavailable", "message": "Tutor service unavailable"},
        )
    # The DB segments below run on the shared sync Session; each is
    # offloaded to a worker thread so a Postgres round-trip never stalls
    # the event loop (and every concurrent SSE stream on this worker).
    explain_instruction, question, search_query, ctx, pending = await asyncio.to_thread(
        _ask_prepare, app_ctx, db, user, payload
    )
    try:
        response = await tutor.ask(
            question,
            payload.class_level,
            canonical_subject(payload.subject),
            chapter=payload.chapter,
            extra_instruction=explain_instruction,
            low_data=payload.low_data,
            context=ctx,
            search_query=search_query,
        )
        await asyncio.to_thread(
            _ask_ledger,
            db,
            user,
            question=question,
            answer=response.answer,
            model=getattr(tutor.provider, "model", None) or tutor.provider.name,
            pending=pending,
        )
        return response
    except ProviderError as exc:
        # BE-01: the provider never produced tokens, but the prompt-side
        # spend is real and already reserved — finalize at zero completion
        # instead of leaving the row an estimate forever.
        model = getattr(tutor.provider, "model", None) or tutor.provider.name
        try:
            await asyncio.to_thread(
                _ask_ledger,
                db,
                user,
                question=question,
                answer=None,
                model=model,
                pending=pending,
            )
        except Exception:  # pragma: no cover - ledger must not mask the 502
            json_log(
                logger,
                logging.WARNING,
                "ledger_finalize_failed",
                error="ask_path",
            )
        # Upstream LLM failure (timeout/exhausted retries/blocked) must be a
        # controlled 502, never an unhandled 500.
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_unavailable", "message": "LLM provider unavailable"},
        ) from exc


# ------------------------------------------------------------------
# Multi-turn tutoring chat (A3)
# ------------------------------------------------------------------


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


@router.post(
    "/tutor/conversations",
    response_model=ConversationOut,
    status_code=201,
    responses=coded(404),
)
def create_conversation(payload: ConversationCreate, db: DbSession, user: CurrentUser):
    student = _student_profile(db, user)
    conv = Conversation(student_id=student.id, title=payload.title)
    db.add(conv)
    db.commit()
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        last_strategy=conv.last_strategy,
        created_at=conv.created_at,
        message_count=0,
    )


@router.get("/tutor/conversations", response_model=list[ConversationOut], responses=coded(404))
def list_conversations(db: DbSession, user: CurrentUser) -> list[ConversationOut]:
    student = _student_profile(db, user)
    rows = (
        db.execute(
            select(Conversation)
            .where(Conversation.student_id == student.id)
            .order_by(Conversation.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    # one grouped COUNT for the whole page (was 1+N per conversation).
    counts = {
        int(cid): int(n)
        for cid, n in db.execute(
            select(ChatMessage.conversation_id, func.count())
            .where(ChatMessage.conversation_id.in_([c.id for c in rows]))
            .group_by(ChatMessage.conversation_id)
        )
    }
    out: list[ConversationOut] = []
    for conv in rows:
        out.append(
            ConversationOut(
                id=conv.id,
                title=conv.title,
                last_strategy=conv.last_strategy,
                created_at=conv.created_at,
                message_count=counts.get(conv.id, 0),
            )
        )
    return out


@router.get("/tutor/conversations/{conversation_id}/messages", response_model=list[ChatMessageOut])
def conversation_messages(
    conversation_id: int,
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[ChatMessageOut]:
    _own_conversation(db, conversation_id, user)
    # cap the payload (was unbounded -- one row per message ever).
    # Newest N are fetched but returned chronological, so existing clients
    # see the same ordering.
    newest = (
        select(ChatMessage.id)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
        .subquery()
    )
    rows = (
        db.execute(
            select(ChatMessage)
            .where(ChatMessage.id.in_(select(newest.c.id)))
            .order_by(ChatMessage.id)
        )
        .scalars()
        .all()
    )
    return [
        ChatMessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            grounded=m.grounded,
            refused_reason=m.refused_reason,
            sources=[SourceRef(**s) for s in (m.sources_json or [])],
            # recomputed from the persisted evidence rows (the DB
            # stores no confidence column; the formula is pure).
            confidence=_answer_confidence(
                m.grounded,
                m.refused_reason,
                [float(s.get("score", 0.0)) for s in (m.sources_json or [])],
            ),
            rating=m.rating,
            created_at=m.created_at,
        )
        for m in rows
    ]


# ------------------------------------------------------------------
# history search + conversation rename/delete
# ------------------------------------------------------------------


@router.patch("/tutor/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: int,
    payload: ConversationUpdate,
    db: DbSession,
    user: CurrentUser,
) -> ConversationOut:
    conv = _own_conversation(db, conversation_id, user)
    new_title = payload.title.strip()
    if new_title:
        conv.title = new_title
    db.commit()
    count = db.execute(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.conversation_id == conv.id)
    ).scalar_one()
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        last_strategy=conv.last_strategy,
        created_at=conv.created_at,
        message_count=count,
    )


@router.delete("/tutor/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, db: DbSession, user: CurrentUser) -> None:
    conv = _own_conversation(db, conversation_id, user)
    db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conv.id))
    db.delete(conv)
    db.commit()


@router.get("/tutor/messages/search", response_model=list[MessageSearchHit])
def search_messages(
    q: Annotated[str, Query(min_length=2, max_length=100)],
    db: DbSession,
    user: CurrentUser,
) -> list[MessageSearchHit]:
    student = _student_profile(db, user)
    conv_ids = select(Conversation.id).where(Conversation.student_id == student.id)
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = db.execute(
        select(ChatMessage, Conversation)
        .join(Conversation, ChatMessage.conversation_id == Conversation.id)
        .where(ChatMessage.conversation_id.in_(conv_ids))
        .where(ChatMessage.content.ilike(f"%{escaped}%", escape="\\"))
        .order_by(ChatMessage.id.desc())
        .limit(25)
    ).all()
    hits: list[MessageSearchHit] = []
    for msg, conv in rows:
        text = msg.content
        pos = text.lower().find(q.lower())
        start = max(0, pos - 40) if pos >= 0 else 0
        snippet = text[start : start + 160]
        hits.append(
            MessageSearchHit(
                conversation_id=conv.id,
                conversation_title=conv.title,
                message_id=msg.id,
                role=msg.role,
                snippet=snippet,
                created_at=msg.created_at,
            )
        )
    return hits


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


class _PreparedTurn(NamedTuple):
    """Everything the two chat-turn routes need after their DB prelude."""

    conv: Conversation
    class_level: int
    history: list[dict[str, str]]
    extra_instruction: str | None
    goal: str
    user_msg: ChatMessage
    image_payload: dict[str, Any] | None
    ctx: RequestContext
    no_vision: bool
    # What conv.last_strategy was before prepare mutated it, so the JSON
    # route can restore it when the LLM call fails after the turn committed.
    prev_strategy: str | None
    # BE-01: the ledger row reserved at prepare time (committed separately),
    # finalized in place by _persist_chat_reply / the stream finally.
    pending_usage: AiUsage | None


def _prepare_chat_turn(
    app_ctx: Ctx,
    db: Session,
    user: User,
    conversation_id: int,
    payload: ChatSendRequest,
    *,
    persist: Literal["flush", "commit"],
) -> _PreparedTurn:
    """DB prelude shared by the JSON and SSE chat turns.

    Runs in a worker thread (asyncio.to_thread): the shared Session is
    sync, and these reads/writes must not stall the event loop that is
    concurrently streaming other users' tokens.
    """
    # AI-002: budget gate before spending upstream tokens.
    check_ai_budget(db, user_id=user.id, settings=app_ctx.settings)
    # BE-01: reserve the ledger row BEFORE the provider call and make it
    # durable in its own transaction -- the budget gate of a concurrent
    # generation must count this in-flight spend, and a disconnect later
    # still leaves the partial spend on the books.
    tutor = app_ctx.tutor
    if tutor is None:  # pragma: no cover - route-level 503 precedes this
        raise HTTPException(
            status_code=503,
            detail={"code": "tutor_unavailable", "message": "Tutor service unavailable"},
        )
    pending_usage: AiUsage | None = reserve_ai_usage(
        db,
        user_id=user.id,
        route="tutor.chat",
        model=getattr(tutor.provider, "model", None) or tutor.provider.name,
        prompt_text=payload.message,
    )
    db.commit()
    conv = _own_conversation(db, conversation_id, user)
    student = _student_profile(db, user)
    class_level = payload.class_level or student.class_level or 6
    history = _chat_history(app_ctx, db, conv.id)
    # vision contract: validated BEFORE anything is persisted.
    image_payload = _validate_chat_image(payload.image)

    # 'আমি বুঝিন': swap to the next explanation strategy and remember it.
    # an explicit strategy request OVERRIDES the rotation and is
    # persisted as last_strategy so the next turn keeps learning from it.
    prev_strategy = conv.last_strategy
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
    if persist == "flush":
        # Flush (not commit): the user turn must not survive a failed LLM
        # call, otherwise the provider error leaves an orphan message behind.
        db.flush()
    else:
        # commit before streaming to release DB session/connection during
        # LLM stream (was flush-only, holding transaction for up to 30s).
        # User turn is persisted alone; assistant turn will be persisted in
        # a short second transaction after the stream.
        db.commit()
        db.refresh(user_msg)
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
    return _PreparedTurn(
        conv=conv,
        class_level=class_level,
        history=history,
        extra_instruction=extra_instruction,
        goal=goal,
        user_msg=user_msg,
        image_payload=image_payload,
        ctx=ctx,
        no_vision=image_payload is not None and _provider_lacks_vision(app_ctx),
        prev_strategy=prev_strategy,
        pending_usage=pending_usage,
    )


def _persist_chat_reply(
    db: Session,
    user: User,
    conv: Conversation,
    payload: ChatSendRequest,
    result: AskResponse,
    *,
    route: str,
    model: str,
    no_vision: bool,
    pending_usage: AiUsage | None = None,
) -> ChatMessage:
    """DB postlude shared by the JSON and SSE chat turns."""
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
    # AI-002/BE-01: finalize the reserve in place (one row per generation
    # with the answer actually produced). Vision refusals never reach a
    # provider: their reserve finalizes at zero completion tokens.
    if not no_vision:
        finalize_ai_usage(db, pending_usage, model=model, answer_text=result.answer)
    db.commit()
    # one question ≈ one minute of study for the daily counters.
    record_activity(db, conv.student_id, questions=1, minutes=1)
    return assistant_msg


@router.post("/tutor/conversations/{conversation_id}/messages", response_model=ChatMessageOut)
async def send_chat_message(
    app_ctx: Ctx, conversation_id: int, payload: ChatSendRequest, db: DbSession, user: CurrentUser
) -> ChatMessageOut:
    """Non-streaming chat turn: persists both sides and returns the reply."""
    tutor = app_ctx.tutor
    if tutor is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "tutor_unavailable", "message": "Tutor service unavailable"},
        )
    # persist="commit" for the same reason the SSE route commits (there it
    # is the comment on _prepare_chat_turn): with "flush" this route held
    # the pooled Postgres connection and its write lock across the whole
    # provider budget (up to 30s), so ~30 concurrent turns exhausted
    # pool_size=10 + overflow=20 per worker and stalled every other
    # endpoint. Audit B-05. The all-or-nothing turn contract is kept by
    # explicitly deleting the committed user turn when the provider fails
    # (see _discard_failed_user_turn) -- the flush path got that behaviour
    # for free from its rollback.
    prepared = await asyncio.to_thread(
        _prepare_chat_turn, app_ctx, db, user, conversation_id, payload, persist="commit"
    )
    if prepared.no_vision:
        # Honest refusal: the mock provider cannot see images at all.
        result = AskResponse(
            answer=VISION_UNSUPPORTED_ANSWER,
            grounded=False,
            sources=[],
            refused_reason="vision_unsupported",
        )
    else:
        try:
            result = await tutor.ask(
                payload.message,
                prepared.class_level,
                canonical_subject(payload.subject),
                prepared.history,
                chapter=payload.chapter,
                extra_instruction=prepared.extra_instruction,
                low_data=payload.low_data,
                context=prepared.ctx,
                image=prepared.image_payload,
            )
        except ProviderError as exc:
            await asyncio.to_thread(_discard_failed_user_turn, db, prepared)
            # BE-01: a failed provider call still spent the prompt-side
            # reserve; finalize it at zero completion in its own transaction
            # so the ledger shows the attempt instead of a phantom estimate.
            try:
                await asyncio.to_thread(
                    finalize_ai_usage,
                    db,
                    prepared.pending_usage,
                    model=getattr(tutor.provider, "model", None) or tutor.provider.name,
                    answer_text=None,
                )
                db.commit()
            except Exception as ledger_exc:  # pragma: no cover - defensive
                json_log(
                    logger,
                    logging.WARNING,
                    "ledger_finalize_failed",
                    error=type(ledger_exc).__name__,
                )
            raise HTTPException(
                status_code=502,
                detail={"code": "llm_unavailable", "message": "LLM provider unavailable"},
            ) from exc

    assistant_msg = await asyncio.to_thread(
        _persist_chat_reply,
        db,
        user,
        prepared.conv,
        payload,
        result,
        route="tutor.chat",
        model=getattr(tutor.provider, "model", None) or tutor.provider.name,
        no_vision=prepared.no_vision,
        pending_usage=prepared.pending_usage,
    )
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


def _discard_failed_user_turn(db: Session, prepared: _PreparedTurn) -> None:
    """Roll the committed user turn back for the JSON route after a provider
    failure (runs in a worker thread; the shared Session is sync).

    The flush path used to get "no orphan turn" for free from its rollback.
    Committing before the LLM call -- necessary so a pooled connection is
    not pinned across a 30s provider request -- moves the cleanup here:
    delete the user message and restore the strategy rotation the prepare
    step had advanced. The external contract for POST .../messages is
    unchanged: a failed provider call leaves neither a reply nor a
    dangling question behind.
    """
    db.delete(prepared.user_msg)
    prepared.conv.last_strategy = prepared.prev_strategy
    db.commit()


@router.post("/tutor/conversations/{conversation_id}/messages/stream")
async def stream_chat_message(
    app_ctx: Ctx, conversation_id: int, payload: ChatSendRequest, db: DbSession, user: CurrentUser
) -> StreamingResponse:
    """SSE streaming chat turn: token events, then one final JSON event."""
    tutor = app_ctx.tutor
    if tutor is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "tutor_unavailable", "message": "Tutor service unavailable"},
        )
    prepared = await asyncio.to_thread(
        _prepare_chat_turn, app_ctx, db, user, conversation_id, payload, persist="commit"
    )
    conv = prepared.conv
    user_msg = prepared.user_msg

    async def event_stream() -> AsyncIterator[str]:
        try:
            final_response: AskResponse | None = None
            if prepared.no_vision:
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
                # The stream is drained through a queue + producer task so a
                # heartbeat can be emitted while NOTHING has arrived yet:
                # retrieval + time-to-first-token can legitimately take tens
                # of seconds, and proxy/LB idle timeouts would otherwise cut
                # the connection before the first token. A `: ping` comment
                # line is SSE-standard and ignored by browsers and by this
                # app's own parser (it only reads `event:`/`data:` lines).
                # (Wrapping __anext__ in wait_for instead would cancel the
                # generator mid-flight on the first timeout — not an option.)
                queue: asyncio.Queue[StreamEvent | ProviderError | None] = asyncio.Queue()

                async def _produce() -> None:
                    try:
                        async for event in tutor.ask_stream(
                            payload.message,
                            prepared.class_level,
                            canonical_subject(payload.subject),
                            prepared.history,
                            chapter=payload.chapter,
                            extra_instruction=prepared.extra_instruction,
                            low_data=payload.low_data,
                            context=prepared.ctx,
                            image=prepared.image_payload,
                        ):
                            await queue.put(event)
                    except ProviderError as exc:
                        await queue.put(exc)
                    finally:
                        await queue.put(None)

                producer = asyncio.create_task(_produce())
                streamed_text: list[str] = []
                try:
                    while True:
                        try:
                            item = await asyncio.wait_for(queue.get(), SSE_HEARTBEAT_SECONDS)
                        except TimeoutError:
                            yield ": ping\n\n"
                            continue
                        if item is None:
                            break
                        if isinstance(item, ProviderError):
                            raise item
                        if item.type == "token" and item.text:
                            streamed_text.append(item.text)
                            token_payload = json.dumps({"text": item.text}, ensure_ascii=False)
                            yield f"event: token\ndata: {token_payload}\n\n"
                        elif item.response is not None:
                            final_response = item.response
                finally:
                    # Client disconnected mid-stream: stop the provider work.
                    producer.cancel()
                    with contextlib.suppress(BaseException):
                        await producer
                    # BE-01: whatever reached the student (even nothing) sits
                    # in the ledger -- the reserve is finalized with the
                    # partial text so a disconnect is accounted for instead
                    # of printing money on one side and burning it on the
                    # other.
                    partial = "".join(streamed_text)
                    try:
                        await asyncio.to_thread(
                            finalize_ai_usage,
                            db,
                            prepared.pending_usage,
                            model=getattr(tutor.provider, "model", None) or tutor.provider.name,
                            answer_text=partial or None,
                        )
                        db.commit()
                    except Exception as ledger_exc:  # pragma: no cover
                        json_log(
                            logger,
                            logging.WARNING,
                            "ledger_finalize_failed",
                            error=type(ledger_exc).__name__,
                        )
            if final_response is None:  # never leak a naked 500 under -O
                # user_msg already committed before stream; no rollback needed
                yield (
                    "event: error\ndata: "
                    + json.dumps({"code": "llm_unavailable"}, ensure_ascii=False)
                    + "\n\n"
                )
                return
            assistant_msg = await asyncio.to_thread(
                _persist_chat_reply,
                db,
                user,
                conv,
                payload,
                final_response,
                route="tutor.chat.stream",
                model=getattr(tutor.provider, "model", None) or tutor.provider.name,
                no_vision=prepared.no_vision,
                pending_usage=prepared.pending_usage,
            )
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
                await asyncio.to_thread(db.rollback)
            yield (
                "event: error\ndata: "
                + json.dumps({"code": "llm_unavailable"}, ensure_ascii=False)
                + "\n\n"
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ------------------------------------------------------------------
# Feedback & privacy-safe product analytics
# ------------------------------------------------------------------


@router.post(
    "/feedback",
    response_model=FeedbackOut,
    status_code=201,
    responses=coded(400, 403, 404),
)
def submit_feedback(payload: FeedbackRequest, db: DbSession, user: CurrentUser) -> FeedbackOut:
    # The "no target" case is a business rule, not a validation failure, so it
    # is a 400: 422 is reserved by FastAPI for request-model validation and its
    # documented body is an array of errors (AUD-0053 / API-02).
    if payload.message_id is None and payload.attempt_id is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "missing_target", "message": "message_id or attempt_id required"},
        )

    def _target_owner_user_id() -> int | None:
        """Resolve the account that owns the rated content (or None if gone)."""
        if payload.message_id is not None:
            conv_owner = db.scalar(
                select(Conversation.student_id)
                .join(ChatMessage, ChatMessage.conversation_id == Conversation.id)
                .where(ChatMessage.id == payload.message_id)
            )
            if conv_owner is None:
                return None
            return db.scalar(select(Student.user_id).where(Student.id == conv_owner))
        attempt_owner = db.scalar(
            select(QuizAttempt.student_id).where(QuizAttempt.id == payload.attempt_id)
        )
        if attempt_owner is None:
            return None
        return db.scalar(select(Student.user_id).where(Student.id == attempt_owner))

    owner_user_id = _target_owner_user_id()
    # Feedback attaches a user-written comment to someone else's chat message
    # or quiz attempt — restrict to the owner (admins may review anything).
    if owner_user_id is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "target_not_found", "message": "Rated content not found"},
        )
    if owner_user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail={"code": "not_owner", "message": "Not allowed to rate this content"},
        )

    row = Feedback(
        user_id=user.id,
        message_id=payload.message_id,
        attempt_id=payload.attempt_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    if payload.message_id is not None and payload.rating in (-1, 1):
        msg = db.get(ChatMessage, payload.message_id)
        if msg is not None:
            # Owner-only message rating (ownership already verified above).
            student_id = db.scalar(select(Student.id).where(Student.user_id == user.id))
            conv_owner_id = db.scalar(
                select(Conversation.student_id).where(Conversation.id == msg.conversation_id)
            )
            if student_id is not None and conv_owner_id == student_id:
                msg.rating = payload.rating
    db.add(row)
    db.commit()
    return FeedbackOut(status="recorded")


@router.get("/admin/feedback", response_model=FeedbackQueuePage)
def admin_feedback_queue(
    db: DbSession,
    admin: AdminUser,
    status: str = Query(default="open", pattern="^(open|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FeedbackQueuePage:
    """triage queue: oldest un-triaged feedback first. Rows carry
    the complaint and nothing more -- reporter identity beyond the id is
    deliberately withheld."""
    stmt = select(Feedback, User.role).join(User, User.id == Feedback.user_id)
    count_stmt = select(func.count()).select_from(Feedback)
    if status == "open":
        stmt = stmt.where(Feedback.triaged.is_(False))
        count_stmt = count_stmt.where(Feedback.triaged.is_(False))
    total = db.execute(count_stmt).scalar_one()
    open_count = db.execute(
        select(func.count()).select_from(Feedback).where(Feedback.triaged.is_(False))
    ).scalar_one()
    rows = db.execute(stmt.order_by(Feedback.id.asc()).limit(limit).offset(offset)).all()
    return FeedbackQueuePage(
        rows=[
            FeedbackAdminRow(
                id=fb.id,
                user_id=fb.user_id,
                role=role,
                rating=fb.rating,
                comment=fb.comment,
                message_id=fb.message_id,
                attempt_id=fb.attempt_id,
                triaged=fb.triaged,
                triaged_at=fb.triaged_at,
                note=fb.triage_note,
                created_at=fb.created_at,
            )
            for fb, role in rows
        ],
        total=total,
        open_count=open_count,
        limit=limit,
        offset=offset,
    )


@router.patch("/admin/feedback/{feedback_id}", response_model=FeedbackAdminRow)
def admin_feedback_triage(
    feedback_id: int, payload: TriageUpdate, db: DbSession, admin: AdminUser
) -> FeedbackAdminRow:
    """Mark a queue item triaged/un-triaged with an optional internal
    note. The note is admin-authored and never returned to end users."""
    fb = db.get(Feedback, feedback_id)
    if fb is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "feedback_not_found", "message": "Feedback not found"},
        )
    fb.triaged = payload.triaged
    fb.triaged_at = datetime.now(UTC).replace(tzinfo=None) if payload.triaged else None
    if payload.note is not None:
        fb.triage_note = payload.note
    db.commit()
    role = db.execute(select(User.role).where(User.id == fb.user_id)).scalar_one()
    return FeedbackAdminRow(
        id=fb.id,
        user_id=fb.user_id,
        role=role,
        rating=fb.rating,
        comment=fb.comment,
        message_id=fb.message_id,
        attempt_id=fb.attempt_id,
        triaged=fb.triaged,
        triaged_at=fb.triaged_at,
        note=fb.triage_note,
        created_at=fb.created_at,
    )


@router.post("/events", status_code=202)
def record_event(
    payload: AnalyticsEvent, request: Request, db: DbSession, user: CurrentUser
) -> dict:
    # Privacy: log only which prop keys were sent, never their values —
    # props are arbitrary client input and may contain personal data.
    json_log(
        logger,
        logging.INFO,
        "product_event",
        name=payload.name,
        props_keys=sorted(payload.props.keys()),
        role=user.role,
    )
    # persist the event server-side after sanitization (drop
    # PII-flavoured keys, primitive values, 40-char strings). The trail
    # table has no FK by design: product analytics survive account
    # deletion as an aggregate-only record (user_id included).
    db.add(
        AnalyticsEventRow(
            user_id=user.id,
            name=payload.name,
            role=user.role,
            props=_sanitize_event_props(dict(payload.props)),
        )
    )
    db.commit()
    return {"status": "accepted"}
