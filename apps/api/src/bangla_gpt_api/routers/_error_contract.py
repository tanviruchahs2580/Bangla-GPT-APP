"""Central error-response contract for the HTTP API.

Every error the API raises is declared here once instead of being restated on
~200 routes. Since F-067 the auth guards answer in the same coded envelope as
business rules (``{"detail": {"code", "message"}}``) so a client can branch on
``detail.code`` for a 401 exactly as it does for a 409; ``MessageDetail``
remains for the few legacy statuses whose body is a plain string (documented
per route via :func:`message`).

FastAPI only auto-documents ``422`` validation, so every other status used to
be *received* by clients while being *absent* from the served OpenAPI document
-- an OpenAPI consumer cannot see the error contract at all. The audit
recorded 199 such undocumented responses (AUD-0055).

``AUTH_GUARD_RESPONSES`` is attached at router construction (FastAPI merges
``APIRouter(responses=...)`` into every operation of that router) and covers
only what *every* authenticated route can return. Business-rule statuses a
specific operation raises are added per route with :func:`coded`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MessageDetail(BaseModel):
    """Body of a legacy plain-string failure (``{"detail": "<message>"}``)."""

    detail: str = Field(examples=["Not authenticated"])


class CodedDetail(BaseModel):
    """Body of a coded failure (``{"detail": {"code", "message"}}``)."""

    detail: dict[str, str] = Field(
        examples=[{"code": "email_taken", "message": "Email already registered"}]
    )


#: 401/403 stable codes, one per refusal reason. Kept here so the SPA's error
#: map and the tests share a single list.
AUTH_CODES = {
    401: ("unauthenticated", "invalid_token", "session_ended", "session_expired", "mfa_required"),
    403: ("insufficient_role", "password_change_required", "impersonation_forbidden"),
}

# 401/403 are raised by the auth dependency on every authenticated route, so
# they are declared once per router rather than once per operation.
AUTH_GUARD_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": CodedDetail, "description": "Missing or invalid credentials"},
    403: {"model": CodedDetail, "description": "Authenticated but not permitted"},
}


def coded(
    *statuses: int,
    description: str = "Business-rule rejection",
) -> dict[int | str, dict[str, Any]]:
    """Declare business-rule statuses that carry a ``{code, message}`` body.

    Used per route, e.g. ``responses=coded(400, 409)`` for an operation that
    can fail those ways.
    """
    return {status: {"model": CodedDetail, "description": description} for status in statuses}


def message(
    *statuses: int,
    description: str = "Rejected",
) -> dict[int | str, dict[str, Any]]:
    """Declare statuses whose body is a plain ``{"detail": "<message>"}``."""
    return {status: {"model": MessageDetail, "description": description} for status in statuses}
