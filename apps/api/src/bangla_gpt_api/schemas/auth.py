"""Pydantic models: auth (split out of schemas.py, C-03)."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)

from bangla_gpt_api.schemas.base import (
    _EMAIL_PATTERN as _EMAIL_PATTERN,
)
from bangla_gpt_api.schemas.base import (  # noqa: F401
    StrictIn as StrictIn,
)


class RegisterRequest(StrictIn):
    email: str = Field(min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=120)
    role: Literal["student", "teacher", "parent"]
    class_level: int | None = Field(default=None, ge=1, le=12)
    # Parental/guardian consent is mandatory for student accounts (minors).
    # Both this and class_level are REQUIRED for role="student", but the
    # coupling cannot be expressed in the OpenAPI schema; the route enforces
    # it as a documented 409 (AUD-0053 / API-02) instead of a model-validator
    # ValueError, which surfaced as an undocumented 422.
    guardian_consent: bool = False
    # optional guardian phone (parent role); stored encrypted when
    # PII_ENC_KEY is configured.
    phone: str | None = Field(default=None, max_length=32)


class RegisterResponse(BaseModel):
    user_id: int
    role: str
    profile_id: int


class LoginRequest(StrictIn):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - an obvious placeholder or a fixture name, not a credential
    must_change_password: bool = False


class ForgotPasswordRequest(StrictIn):
    email: str = Field(min_length=5, max_length=255)


class ResetPasswordRequest(StrictIn):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(StrictIn):
    """Verification code only — no password fields (V1 fix)."""

    token: str = Field(min_length=16, max_length=256)


class ResendVerificationRequest(StrictIn):
    """Unauthenticated resend for users stuck at login with email_unverified.

    The login endpoint issues no token for unverified accounts, so the
    previous authed-only resend was unreachable exactly when needed.
    Email is optional so already-authed callers can omit it (server uses
    their identity); unauthenticated callers must supply it. The endpoint
    always answers 202 with a generic body to avoid account enumeration.
    """

    email: str | None = Field(default=None, min_length=5, max_length=255)


class ChangePasswordRequest(StrictIn):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class StatusAcceptedOut(BaseModel):
    """Generic 202 body for the anti-enumeration endpoints (H-02: was ``dict``)."""

    status: Literal["accepted"]


class MfaEnrollOut(BaseModel):
    """Fresh (unstored) secret + authenticator URI. Nothing is enabled yet."""

    secret: str
    otpauth_uri: str


class MfaDisabledOut(BaseModel):
    """Result of a verified MFA disable (H-02: typed, was ``dict``)."""

    disabled: Literal[True]


class MfaEnabledOut(BaseModel):
    """Result of a verified MFA enrollment (H-02: typed, was ``dict``)."""

    enabled: Literal[True]


class MfaVerifyIn(StrictIn):
    secret: str = Field(min_length=16, max_length=64)
    code: str = Field(min_length=6, max_length=6)


class MfaDisableIn(StrictIn):
    password: str = Field(min_length=1, max_length=128)


class MfaChallengeIn(StrictIn):
    mfa_token: str = Field(min_length=16, max_length=2048)
    code: str = Field(min_length=6, max_length=6)


class DataExportResponse(BaseModel):
    """Self-service GDPR-style export of everything we store about the user.

    F-063: this used to carry the profile, the quiz attempts and the guardian
    links and nothing else. For a student that omitted every conversation and
    every chat message -- the single largest body of personal data the product
    holds about a child, and the data most likely to be subject to a subject
    access request or a parental request. A portability response that silently
    stops at quiz scores is not a portability response.
    """

    user: dict
    profile: dict | None
    quiz_attempts: list[dict]
    parent_links: list[dict]
    conversations: list[dict] = []
    chat_messages: list[dict] = []
    learning_activity: list[dict] = []
