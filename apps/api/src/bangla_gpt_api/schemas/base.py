"""Pydantic models: base (split out of schemas.py, C-03)."""

from __future__ import annotations

from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

MAX_QUIZ_QUESTIONS = 25


class StrictIn(BaseModel):
    """Base for every request body: undeclared fields are a 422, not silence.

    Pydantic's default (``extra="ignore"``) silently drops unknown keys, so a
    client typo -- or a client newer than the deployed server -- used to get a
    200 with the field quietly discarded (H-02 / AUD-HI-004). Every model a
    route accepts as a request body inherits this base, so the served OpenAPI
    marks each input object ``additionalProperties: false`` and
    ``tests/test_r3_ws3_schema_strictness.py`` holds the line for new routes.

    Response models deliberately do NOT inherit this base: they are built from
    ORM rows, where "extra" attributes are expected and ignored.
    """

    model_config = ConfigDict(extra="forbid")


class SourceRef(BaseModel):
    book: str
    chapter: str
    section: str | None = None
    page: int | None = None
    score: float
    # sanitized evidence excerpt shown in the source → evidence modal.
    excerpt: str | None = None


_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class MeResponse(BaseModel):
    user_id: int
    email: str
    role: str
    profile_id: int | None
    name: str | None
    class_level: int | None
    phone: str | None = None  # decrypted guardian phone, owner only


class QuizQuestionPublic(BaseModel):
    id: str
    question_text: str
    options: list[str]


class UserPublic(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime


class WeakCell(BaseModel):
    asked: int
    correct: int
    accuracy: float | None = None
    read: bool = False  # tutor/reading signal from chapter progress


class ChatImageIn(StrictIn):
    """Optional inline image on a chat turn. Validated in the route:
    mime must be in _IMAGE_MIME_ALLOWED, the base64 payload must decode and
    the decoded bytes must stay <= _IMAGE_MAX_BYTES; violations answer with
    422 {"code": "image_invalid"}."""

    mime_type: str = Field(min_length=1, max_length=64)
    data_base64: str = Field(min_length=1)
