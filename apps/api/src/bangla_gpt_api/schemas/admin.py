"""Pydantic models: admin (split out of schemas.py, C-03)."""

from __future__ import annotations

from datetime import datetime

from pydantic import (
    BaseModel,
    Field,
)

from bangla_gpt_api.schemas.base import (  # noqa: F401
    StrictIn as StrictIn,
)
from bangla_gpt_api.schemas.base import (
    UserPublic as UserPublic,
)


class AuditRowOut(BaseModel):
    """one audit_log row as seen by admins. detail never contains
    message content or PII -- only ids and outcome metadata."""

    id: int
    created_at: datetime
    actor_user_id: int | None
    actor_role: str
    action: str
    target: str | None
    detail: dict


class AdminAuditPage(BaseModel):
    rows: list[AuditRowOut]
    total: int
    limit: int
    offset: int


class ImpersonateRequest(StrictIn):
    reason: str = Field(min_length=3, max_length=200)


class ImpersonateOut(BaseModel):
    access_token: str
    user_id: int
    role: str
    expires_in_min: int


class TriageUpdate(StrictIn):
    """feedback triage queue transition (admin-only).

    Note is free text written BY the admin, so its length is bounded and
    the endpoint records who set it; it never enters user-facing payloads.
    """

    triaged: bool
    note: str | None = Field(default=None, max_length=500)


class AdminOverview(BaseModel):
    users_total: int
    students: int
    teachers: int
    admins: int
    parents: int
    quiz_attempts_graded: int
    avg_score_pct: float | None


class AdminUsersPage(BaseModel):
    total: int
    items: list[UserPublic]


class RefusalAuditOut(BaseModel):
    """refusal audit: aggregate counts only, never message content."""

    days: int
    total_refusals: int
    by_reason: dict[str, int]
    by_class: dict[str, int]
    last_refusal_at: datetime | None = None


class AdminSchoolStatsOut(BaseModel):
    """One row of the admin school list with learning-health counts."""

    id: int
    name: str
    code: str
    created_at: datetime
    teachers: int
    classrooms: int
    students: int
    sessions_7d: int


class AdminAiQualityOut(BaseModel):
    """Counts only, never message content."""

    days: int
    answers_total: int
    grounded_count: int
    ungrounded_count: int
    refusals_total: int
    refusals_by_reason: dict[str, int] = {}
    thumbs_up: int = 0
    thumbs_down: int = 0
    # confidence < 0.5 under the documented formula (see main._answer_confidence)
    low_confidence_count: int = 0
    # ChatMessage carries no model column -> always empty today (audit finding).
    by_model: dict[str, int] = {}
    # AI-002: estimated LLM spend (USD) over the same window, from ai_usage.
    cost_usd_total: float = 0.0
    cost_usd_by_model: dict[str, float] = {}
    # A10-03: the version identities behind these counts (prompt registry,
    # index fingerprint, embedding model, thresholds version, golden hashes),
    # read from the artifacts that own them by evaluation.version_board.
    # ``{}`` means the caller could not build the payload; the board renders
    # an explicit "unknown" rather than a blank.
    versions: dict = {}
