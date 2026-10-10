"""Central error-response contract for the HTTP API.

The API raises its errors with ``HTTPException`` (plain ``detail`` strings for
auth guards, ``{"code", "message"}`` objects for business rules). FastAPI only
auto-documents ``422`` validation, so every one of those statuses used to be
*received* by clients while being *absent* from the served OpenAPI document --
an OpenAPI consumer cannot see the error contract at all. The audit recorded
199 such undocumented responses (AUD-0055).

The two shapes are declared once here instead of being restated on ~200 routes:
``AUTH_GUARD_RESPONSES`` is attached at router construction (FastAPI merges
``APIRouter(responses=...)`` into every operation of that router) and covers
only what *every* authenticated route can return. Business-rule statuses a
specific operation raises are added per route with :func:`coded`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MessageDetail(BaseModel):
    """Body of an auth-guard failure (``{"detail": "<message>"}``)."""

    detail: str = Field(examples=["Not authenticated"])


class CodedDetail(BaseModel):
    """Body of a business-rule failure (``{"detail": {"code", "message"}}``)."""

    detail: dict[str, str] = Field(
        examples=[{"code": "email_taken", "message": "Email already registered"}]
    )


# 401/403 are raised by the auth dependency on every authenticated route, so
# they are declared once per router rather than once per operation.
AUTH_GUARD_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": MessageDetail, "description": "Missing or invalid credentials"},
    403: {"model": MessageDetail, "description": "Authenticated but not permitted"},
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
