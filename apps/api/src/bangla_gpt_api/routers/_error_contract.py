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

Catalog
-------
The third part of the contract is the **error-code catalog** below
(``ERROR_CATALOG``). Every business-rule failure that ships a machine-readable
``code`` must declare it here with its status and the exact key set of its
body, so a typed client can switch on codes instead of on English prose.
``tests/test_cd_error_contract.py`` scans the source and fails when a raised
code is missing from the catalog, when a status drifts, or when a body
gains/loses keys -- the catalog cannot rot silently. Adding a code means adding
one ``ErrorSpec`` row here in the same commit that raises it.

The wire shapes themselves are frozen (no behaviour change was part of adding
the catalog):

1. ``{"detail": "<message>"}`` -- guards and single-message failures.
2. ``{"detail": {"code": ..., "message": ..., <declared extras>}}`` -- business
   rules. ``review_required`` is the one legacy body without ``message``; its
   exact key set is recorded in the catalog rather than "fixed", because
   changing it would change the wire.
3. ``{"detail": [{"loc": [...], "msg": ...}]}`` -- FastAPI's own
   request/response validation shape, reproduced verbatim at the single site
   listed in ``FRAMEWORK_VALIDATION_SITES``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

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


@dataclass(frozen=True)
class ErrorSpec:
    """One catalogued error body.

    ``status`` is the HTTP status the code is raised with; ``keys`` is the
    exact key set of the ``detail`` object (order-insensitive); ``message`` is
    the primary English message at the reference site -- None where the message
    is composed per call (an f-string, or absent).
    """

    status: int
    keys: tuple[str, ...]
    message: str | None


ERROR_CATALOG: Final[dict[str, ErrorSpec]] = {
    "account_locked": ErrorSpec(
        429, ("code", "message"), "Account temporarily locked after repeated failed sign-ins"
    ),
    "ai_budget_exceeded": ErrorSpec(
        429, ("code", "message"), "Monthly AI budget exhausted. Please try again next month."
    ),
    "already_used": ErrorSpec(409, ("code", "message"), "Invite already redeemed"),
    # The only body with the two numeric extras; clients read them to render
    # "you answered N of M".
    "answer_count_mismatch": ErrorSpec(
        400,
        ("code", "message", "expected", "received"),
        "Answer count does not match question count",
    ),
    "bad_credentials": ErrorSpec(401, ("code", "message"), "Incorrect email or password"),
    "bad_mfa_code": ErrorSpec(401, ("code", "message"), "Invalid authenticator code"),
    # Three sites share the code with different messages; the catalog records
    # the code and shape, the message is copy.
    "bad_mfa_token": ErrorSpec(401, ("code", "message"), "Not an MFA step-up token"),
    "class_level_required": ErrorSpec(
        409, ("code", "message"), "class_level is required when role is 'student'"
    ),
    "code_used": ErrorSpec(409, ("code", "message"), "Invite already used"),
    "consent_not_accepted": ErrorSpec(400, ("code", "message"), "acceptance required"),
    "content_read_only": ErrorSpec(
        403,
        ("code", "message"),
        "This chapter content was authored by another school and is read-only",
    ),
    "conversation_not_found": ErrorSpec(404, ("code", "message"), "Conversation not found"),
    "direct_link_disabled": ErrorSpec(
        410, ("code", "message"), "Use the student's invite code via /parents/link/invite"
    ),
    "email_taken": ErrorSpec(409, ("code", "message"), "Email already registered"),
    "email_unverified": ErrorSpec(403, ("code", "message"), "Email verification required"),
    "empty_query": ErrorSpec(422, ("code", "message"), "Query must not be blank"),
    "empty_roster": ErrorSpec(422, ("code", "message"), "Classroom has no students yet"),
    "feedback_not_found": ErrorSpec(404, ("code", "message"), "Feedback not found"),
    "guardian_consent_required": ErrorSpec(
        409, ("code", "message"), "guardian_consent is required when role is 'student'"
    ),
    "image_invalid": ErrorSpec(422, ("code", "message"), "Unsupported image mime type"),
    "image_type_mismatch": ErrorSpec(
        422, ("code", "message"), "Image content does not match the declared mime type"
    ),
    "impersonation_forbidden": ErrorSpec(403, ("code", "message"), "admins cannot be impersonated"),
    "index_unavailable": ErrorSpec(503, ("code", "message"), "Curriculum index unavailable"),
    "internal_error": ErrorSpec(500, ("code", "message"), "An unexpected error occurred"),
    "invalid_code": ErrorSpec(404, ("code", "message"), "Invalid invite code"),
    "invalid_explanation_style": ErrorSpec(
        422, ("code", "message"), "explanation_style must be simple|standard|detailed"
    ),
    "invalid_invite": ErrorSpec(400, ("code", "message"), "Invalid or expired invite code"),
    "invalid_subject_focus": ErrorSpec(
        422, ("code", "message"), "subject_focus must be a 1-60 character string or null to clear"
    ),
    "invalid_token": ErrorSpec(400, ("code", "message"), "Invalid or expired verification code"),
    "invite_expired": ErrorSpec(410, ("code", "message"), "Invite code has expired"),
    "llm_unavailable": ErrorSpec(502, ("code", "message"), "LLM provider unavailable"),
    "missing_target": ErrorSpec(400, ("code", "message"), "message_id or attempt_id required"),
    "mixed_class_levels": ErrorSpec(
        422, ("code", "message"), "Select students from a single class"
    ),
    "no_quiz_for_filter": ErrorSpec(
        422, ("code", "message"), "No questions for this class/subject/chapter yet"
    ),
    "no_school": ErrorSpec(404, ("code", "message"), "No school linked to this account"),
    "no_student_profile": ErrorSpec(404, ("code", "message"), "Student profile not found"),
    "not_allowed": ErrorSpec(403, ("code", "message"), "Not allowed to access this conversation"),
    "not_found": ErrorSpec(404, ("code", "message"), "Revision item not found"),
    "not_impersonation": ErrorSpec(
        403, ("code", "message"), "only an impersonation session can exit here"
    ),
    "not_owner": ErrorSpec(403, ("code", "message"), "Not allowed to rate this content"),
    "other_school": ErrorSpec(403, ("code", "message"), "Student is outside your school"),
    "password_too_common": ErrorSpec(
        400, ("code", "message"), "That password is too common. Choose something harder to guess."
    ),
    "password_unchanged": ErrorSpec(
        409, ("code", "message"), "New password must differ from the current one"
    ),
    "provider_unavailable": ErrorSpec(503, ("code", "message"), "LLM provider not configured"),
    "rate_limited": ErrorSpec(429, ("code", "message"), "Rate limit exceeded"),
    # Legacy body: 409 carries only the unreviewed question ids, no message.
    # Frozen as-is (a wire change would break the teachers' client).
    "review_required": ErrorSpec(409, ("code", "unreviewed"), None),
    "revocation_unavailable": ErrorSpec(
        503, ("code", "message"), "session revocation store is unreachable; try again shortly"
    ),
    "target_not_found": ErrorSpec(404, ("code", "message"), "Rated content not found"),
    "tutor_unavailable": ErrorSpec(503, ("code", "message"), "Tutor service unavailable"),
    # Message is composed per call ("Unsupported preference key: <key>").
    "unknown_learning_pref": ErrorSpec(422, ("code", "message"), None),
    # Message is composed per call ("Student <id> not found").
    "unknown_student": ErrorSpec(404, ("code", "message"), None),
}

# The single site that raises FastAPI's own validation-error list shape (it
# mirrors what RequestValidationError would have produced for the response
# model). Registered so the shape test can tell "documented" from "drifted".
FRAMEWORK_VALIDATION_SITES: Final[frozenset[str]] = frozenset(
    {"routers/teacher_content.py:teacher_generate_document"}
)
