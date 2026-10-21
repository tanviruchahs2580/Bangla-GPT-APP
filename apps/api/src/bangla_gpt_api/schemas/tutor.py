"""Pydantic models: tutor (split out of schemas.py, C-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
)

from bangla_gpt_api.schemas.base import (  # noqa: F401
    ChatImageIn as ChatImageIn,
)
from bangla_gpt_api.schemas.base import (
    SourceRef as SourceRef,
)
from bangla_gpt_api.schemas.base import (
    StrictIn as StrictIn,
)

ChatStrategy = Literal["simple", "example", "book_language", "steps", "analogy"]


ExplanationStyle = Literal["simple", "standard", "detailed"]


class QuizExplainContext(StrictIn):
    """quiz review context handed to the tutor for a wrong item."""

    question: str = Field(min_length=3, max_length=500)
    options: list[str] = Field(min_length=2, max_length=8)
    correct_index: int = Field(ge=0)
    user_answer: int = Field(ge=-1)
    chapter: str | None = Field(default=None, max_length=200)


class AskRequest(StrictIn):
    question: str = Field(min_length=3, max_length=1000)
    class_level: int = Field(ge=1, le=12)
    # Bounded to the columns these are written to (subject VARCHAR(60),
    # chapter VARCHAR(200)) and to what is sensible to interpolate into the
    # provider prompt. Unbounded, a long value was a 500 on PostgreSQL
    # (StringDataRightTruncation on the INSERT) and a free prompt-bloat
    # channel on the AI routes.
    subject: str | None = Field(default=None, max_length=60)
    # optional chapter context from the unified workspace "জিজ্ঞাসা" tab.
    chapter: str | None = Field(default=None, max_length=200)
    # 'বুঝিয়ে দাও' — structured context of a wrong quiz answer.
    explain: QuizExplainContext | None = None
    # low-data mode — request a short answer to cut payload size.
    # StrictBool: the served contract declares a JSON boolean, while
    # Pydantic's lax bool would also accept 0/1 (API-02 drift).
    low_data: StrictBool = False


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    sources: list[SourceRef] = []
    # Machine-readable refusal category ('unsafe_content' | 'insufficient_evidence').
    refused_reason: str | None = None
    # Soft post-generation signal that the answer leans on the cited evidence.
    citation_verified: bool | None = None
    # Programmatic verdict on the question's arithmetic when one was evaluable:
    # 'verified' | 'mismatch' | 'unverified' | 'not_applicable' (A6-04). An
    # enforced 'mismatch' never reaches clients as an answer; the label exists
    # so the UI can say "unverified" honestly instead of implying a check.
    numeric_check: str | None = None
    # Bounded internal grounding signal (breadth+depth of the retrieved
    # sources; formula in services/safety.answer_confidence). It is NOT a
    # calibrated probability: do not render it as a percentage (A6-05).
    confidence: float | None = None


class ConversationCreate(StrictIn):
    title: str | None = Field(default=None, max_length=120)


class ConversationUpdate(StrictIn):
    """rename a conversation."""

    title: str = Field(min_length=1, max_length=120)


class MessageSearchHit(BaseModel):
    """one message matching the history search query."""

    conversation_id: int
    conversation_title: str | None
    message_id: int
    role: str
    snippet: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    title: str | None
    # last explanation strategy (drives the 'আমি বুঝিন' re-teach cycle).
    last_strategy: str | None = None
    created_at: datetime
    message_count: int = 0


class ChatSendRequest(StrictIn):
    message: str = Field(min_length=3, max_length=1000)
    class_level: int | None = Field(default=None, ge=1, le=12)
    subject: str | None = Field(default=None, max_length=60)
    # optional chapter context chip.
    chapter: str | None = Field(default=None, max_length=200)
    # 'আমি বুঝিন' — force the next re-teach strategy for this turn.
    reteach: bool = False
    # low-data mode — request a short answer to cut payload size.
    # StrictBool: the served contract declares a JSON boolean, while
    # Pydantic's lax bool would also accept 0/1 (API-02 drift).
    low_data: StrictBool = False
    # explicit strategy -- overrides the reteach rotation for this
    # turn and persists as Conversation.last_strategy. Literal typing makes
    # an invalid value a 422 without any route code.
    strategy: ChatStrategy | None = None
    # vision contract: optional inline image (validated in route).
    image: ChatImageIn | None = None


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    grounded: bool | None = None
    refused_reason: str | None = None
    sources: list[SourceRef] = []
    rating: int | None = None
    created_at: datetime
    # honest numeric confidence (formula documented in
    # main._answer_confidence). None for user turns / pre-wave answers read
    # before this field existed is impossible -- it is always computed.
    confidence: float | None = None


class FeedbackRequest(StrictIn):
    # -1 = down, +1 = up, 0 = no verdict. 0 stays valid deliberately: the field
    # is required, so it is the only way to send a comment with no thumbs
    # answer, and an aggregate that counts only -1/+1 is then correct rather
    # than incomplete. Tightening this to Literal[-1, 1] removes comment-only
    # feedback and breaks the coded 400 that a body with no target must get.
    rating: int = Field(ge=-1, le=1)
    message_id: int | None = None
    attempt_id: int | None = None
    comment: str | None = Field(default=None, max_length=500)


class FeedbackOut(BaseModel):
    """Explicit success body for POST /feedback (AUD-0052: served contract
    must match behaviour; the handler used to return an untyped dict)."""

    status: Literal["recorded"]


class AnalyticsEvent(StrictIn):
    """Privacy-safe product event; logged as structured JSON, never PII."""

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.]+$")
    props: dict[str, str | int | bool] = Field(default_factory=dict)
