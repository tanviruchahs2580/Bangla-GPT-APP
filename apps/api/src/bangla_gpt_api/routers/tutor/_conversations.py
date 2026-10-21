"""Tutor routes, split by surface (C-03): the single-shot ask, the
conversation history, the streamed chat, feedback, and product events.

_conversations — C-03 split of ``routers/tutor.py``: same paths, same order, same
guards as the single module it came from.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import delete, func, select

from bangla_gpt_api.db.models import (
    ChatMessage,
    Conversation,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES, coded
from bangla_gpt_api.schemas import (
    ChatMessageOut,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    MessageSearchHit,
    SourceRef,
)

from .._pagination import WindowPage
from ..common import (
    _answer_confidence,
    _student_profile,
)
from ..deps import (
    CurrentUser,
    DbSession,
)
from ._shared import (  # noqa: F401
    _own_conversation as _own_conversation,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)


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
    page: WindowPage,
) -> list[ChatMessageOut]:
    _own_conversation(db, conversation_id, user)
    # C-10: one pagination convention. The offsetwalks the newest-N candidate
    # window (skip the most recent `offset`, return the next `limit`), and the
    # selected slice is returned chronological, so existing clients see the
    # same ordering.
    newest = (
        select(ChatMessage.id)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id.desc())
        .offset(page.offset)
        .limit(page.limit)
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
