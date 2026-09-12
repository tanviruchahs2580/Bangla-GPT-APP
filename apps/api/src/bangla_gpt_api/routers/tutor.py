"""Tutor Routes — split from the main.py god-module (ARCH-001).

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via :mod:`.deps`, shared helpers via :mod:`.common`.
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    AnalyticsEventRow,
    ChatMessage,
    Conversation,
    Feedback,
    Student,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.providers import (
    ProviderError,
)
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
from bangla_gpt_api.services.costs import check_ai_budget, record_ai_usage
from bangla_gpt_api.services.quiz_explain import quiz_explain_instruction
from bangla_gpt_api.services.tutor import VISION_UNSUPPORTED_ANSWER

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
    _is_mock_provider,
)

router = APIRouter()

logger = logging.getLogger(__name__)


@router.post("/tutor/ask", response_model=AskResponse)
async def ask(app_ctx: Ctx, payload: AskRequest, db: DbSession, user: CurrentUser) -> AskResponse:
    tutor = app_ctx.tutor
    if tutor is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "tutor_unavailable", "message": "Tutor service unavailable"},
        )
    # AI-002: budget gate before spending upstream tokens.
    check_ai_budget(db, user_id=user.id, settings=app_ctx.settings)
    try:
        explain_instruction = quiz_explain_instruction(payload.explain) if payload.explain else None
        # S1.7: retrieve on the quiz topic itself — the generic
        # 'explain this' phrasing carries no subject keywords. S4.5: the
        # phrasing is dropped from the RETRIEVE/gate query entirely (it
        # diluted coverage below the grounding gate); it stays in the
        # prompt so the model still sees the student's own words.
        question = payload.question
        search_query: str | None = None
        if payload.explain:
            question = f"{payload.question}\n{payload.explain.question}"
            search_query = payload.explain.question
        # S4.1: every AI call carries the central education context.
        ctx = _request_context(
            db,
            user,
            class_level=payload.class_level,
            subject=canonical_subject(payload.subject),
            chapter=payload.chapter,
            goal="quiz_explain" if payload.explain else "question",
        )
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
        # AI-002: ledger the generation (adds only; this commit persists it).
        record_ai_usage(
            db,
            user_id=user.id,
            route="tutor.ask",
            model=getattr(tutor.provider, "model", None) or tutor.provider.name,
            prompt_text=question,
            answer_text=response.answer,
        )
        db.commit()
        return response
    except ProviderError as exc:
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


@router.post("/tutor/conversations", response_model=ConversationOut, status_code=201)
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


@router.get("/tutor/conversations", response_model=list[ConversationOut])
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
    # S5.5: one grouped COUNT for the whole page (was 1+N per conversation).
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
    # S5.5: cap the payload (was unbounded -- one row per message ever).
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
            # Wave 2: recomputed from the persisted evidence rows (the DB
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
# S1.8: history search + conversation rename/delete
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
    history = [{"role": m.role, "content": m.content} for m in reversed(rows)]
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
    conv = _own_conversation(db, conversation_id, user)
    student = _student_profile(db, user)
    class_level = payload.class_level or student.class_level or 6
    history = _chat_history(app_ctx, db, conv.id)
    # Wave 2 vision contract: validated BEFORE anything is persisted.
    image_payload = _validate_chat_image(payload.image)

    # S1.5 'আমি বুঝিন': swap to the next explanation strategy and remember it.
    # Wave 2: an explicit strategy request OVERRIDES the rotation and is
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

    if image_payload is not None and _is_mock_provider(app_ctx):
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
    if image_payload is None or not _is_mock_provider(app_ctx):
        record_ai_usage(
            db,
            user_id=user.id,
            route="tutor.chat",
            model=getattr(tutor.provider, "model", None) or tutor.provider.name,
            prompt_text=payload.message,
            answer_text=result.answer,
        )
    db.commit()
    # S1.9: one question ≈ one minute of study for the daily counters.
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
    conv = _own_conversation(db, conversation_id, user)
    student = _student_profile(db, user)
    class_level = payload.class_level or student.class_level or 6
    history = _chat_history(app_ctx, db, conv.id)
    # Wave 2 vision contract: validated BEFORE anything is persisted.
    image_payload = _validate_chat_image(payload.image)

    # S1.5 'আমি বুঝিন': swap to the next explanation strategy and remember it.
    # Wave 2: explicit strategy OVERRIDES the rotation (persisted likewise).
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
    # F-PERF-06: commit before streaming to release DB session/connection during LLM stream
    # (was flush-only, holding transaction for up to 30s). User turn is persisted alone;
    # assistant turn will be persisted in a short second transaction after stream.
    db.commit()
    db.refresh(user_msg)
    # S4.1: build the context before streaming so the log line lands once.
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
    mock_vision = image_payload is not None and _is_mock_provider(app_ctx)

    async def event_stream() -> AsyncIterator[str]:
        try:
            final_response: AskResponse | None = None
            if mock_vision:
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
                async for event in tutor.ask_stream(  # type: ignore[union-attr]
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
                    elif event.response is not None:
                        final_response = event.response
            if final_response is None:  # never leak a naked 500 under -O
                # F-PERF-06: user_msg already committed before stream; no rollback needed
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
            if not mock_vision:
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
                # Wave 2: additive grounding-confidence in [0,1] (see
                # _answer_confidence for the documented formula).
                "confidence": _answer_confidence(
                    final_response.grounded,
                    final_response.refused_reason,
                    source_scores(final_response.sources),
                ),
            }
            yield ("event: done\ndata: " + json.dumps(done_payload, ensure_ascii=False) + "\n\n")
        except ProviderError:
            # F-PERF-06: user turn already persisted; do not rollback
            try:
                db.rollback()
            except Exception:
                pass
            yield (
                "event: error\ndata: "
                + json.dumps({"code": "llm_unavailable"}, ensure_ascii=False)
                + "\n\n"
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ------------------------------------------------------------------
# Feedback & privacy-safe product analytics (B12)
# ------------------------------------------------------------------


@router.post("/feedback", status_code=201)
def submit_feedback(payload: FeedbackRequest, db: DbSession, user: CurrentUser) -> dict:
    if payload.message_id is None and payload.attempt_id is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "missing_target", "message": "message_id or attempt_id required"},
        )
    row = Feedback(
        user_id=user.id,
        message_id=payload.message_id,
        attempt_id=payload.attempt_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    if payload.message_id is not None:
        msg = db.get(ChatMessage, payload.message_id)
        if msg is not None and payload.rating in (-1, 1):
            msg.rating = payload.rating
    db.add(row)
    db.commit()
    return {"status": "recorded"}


@router.get("/admin/feedback", response_model=FeedbackQueuePage)
def admin_feedback_queue(
    db: DbSession,
    admin: AdminUser,
    status: str = Query(default="open", pattern="^(open|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FeedbackQueuePage:
    """S5.10 triage queue: oldest un-triaged feedback first. Rows carry
    the complaint and nothing more -- reporter identity beyond the id is
    deliberately withheld (R11)."""
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
    # Wave 1: persist the event server-side after sanitization (drop
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
