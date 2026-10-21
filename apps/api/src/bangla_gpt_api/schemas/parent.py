"""Pydantic models: parent (split out of schemas.py, C-03)."""

from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    Field,
)

from bangla_gpt_api.schemas.base import (  # noqa: F401
    StrictIn as StrictIn,
)


class ParentLinkRequest(StrictIn):
    student_id: int = Field(ge=1)


class ParentInviteLinkRequest(StrictIn):
    code: str = Field(min_length=8, max_length=128)


class ParentReportOut(BaseModel):
    """JSON report for one linked child over a window. Server returns
    suggestion CODES + params only; the client renders the copy (i18n)."""

    student_id: int
    name: str
    class_level: int
    period: str  # weekly | monthly
    window_start: str
    window_end: str
    quizzes_taken: int
    quizzes_graded: int
    avg_score_pct: float | None = None
    chapters_read: int
    chapters_completed: int
    questions_asked: int
    weak_chapters: list[str] = []  # same source as the weekly digest (<60%)
    strengths: list[str] = []  # chapter accuracy >= 85 in the window
    suggestion_code: str
    suggestion_params: dict[str, Any] = {}


class ParentLinkOut(BaseModel):
    """Result of a successful parent↔student link (H-02: typed, was ``dict``)."""

    linked: bool
    parent_id: int
    student_id: int


class ParentInviteCodeOut(BaseModel):
    """A freshly generated single-use invite code (H-02: typed, was ``dict``)."""

    code: str
    expires_in_minutes: int
