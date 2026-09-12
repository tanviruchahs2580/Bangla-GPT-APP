"""Auth Routes — split from the main.py god-module (ARCH-001).

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via :mod:`.deps`, shared helpers via :mod:`.common`.
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.auth.mfa import new_secret, otpauth_uri, verify_code
from bangla_gpt_api.auth.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    EmailVerification,
    Parent,
    PasswordReset,
    Student,
    Teacher,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MfaChallengeIn,
    MfaDisableIn,
    MfaEnrollOut,
    MfaVerifyIn,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from bangla_gpt_api.security import encrypt_pii
from bangla_gpt_api.services.mailer import send_mail, smtp_configured

from .deps import (
    CONSENT_VERSION,
    Ctx,
    CurrentUser,
    DbSession,
)

router = APIRouter()

logger = logging.getLogger(__name__)


@router.post("/auth/register", response_model=RegisterResponse, status_code=201)
def register(
    app_ctx: Ctx, request: Request, payload: RegisterRequest, db: DbSession
) -> RegisterResponse:
    email = payload.email.strip().lower()
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "email_taken", "message": "Email already registered"},
        )
    # Email verification is enforced only when SMTP delivery exists;
    # otherwise accounts are trusted as verified (dev/small deployments).
    verified = not smtp_configured(app_ctx.settings)
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        email_verified=verified,
    )
    db.add(user)
    try:
        # Unique violation on users.email surfaces here when a concurrent
        # registration won the race between our check and this insert.
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "email_taken", "message": "Email already registered"},
        ) from exc
    profile: Student | Teacher | Parent
    if payload.role == "student":
        consent_ip = request.client.host if request.client else None
        profile = Student(
            name=payload.name.strip(),
            class_level=payload.class_level,
            user_id=user.id,
            consent_ip=consent_ip,
            consent_at=datetime.now(UTC),
            consent_version=CONSENT_VERSION,
        )
    elif payload.role == "parent":
        phone = payload.phone.strip() if payload.phone and payload.phone.strip() else None
        profile = Parent(
            name=payload.name.strip(),
            user_id=user.id,
            # S5.6: guardian phone encrypted at rest when PII_ENC_KEY is set.
            phone_enc=encrypt_pii(phone, app_ctx.settings.pii_enc_key),
        )
    else:
        profile = Teacher(name=payload.name.strip(), user_id=user.id)
    db.add(profile)
    db.commit()
    if not verified:
        _send_verification_email(db, app_ctx.settings, user)
    return RegisterResponse(user_id=user.id, role=user.role, profile_id=profile.id)


def _send_verification_email(db: Session, settings: Settings, user: User) -> None:
    token = secrets.token_urlsafe(32)
    db.add(
        EmailVerification(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )
    )
    db.commit()
    send_mail(
        settings,
        to=user.email,
        subject="ইমেইল যাচাই / Verify your email",
        body=(
            "Bangla GPT Tutor-এ স্বাগতম! "
            "ইমেইল যাচাই করতে নিচের কোডটি "
            "অ্যাপের ঘরে দিন (২৪ ঘণ্টা বৈধ):\n\n"
            f"{token}\n"
        ),
    )


@router.post("/auth/verify-email", response_model=TokenResponse)
def verify_email(app_ctx: Ctx, payload: VerifyEmailRequest, db: DbSession) -> TokenResponse:
    """Complete email verification with the token from the mail.

    On success the account is marked verified and a session is issued.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    row = db.execute(
        select(EmailVerification).where(
            EmailVerification.token_hash == hashlib.sha256(payload.token.encode()).hexdigest(),
            EmailVerification.used_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None or row.expires_at < now:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_token", "message": "Invalid or expired verification code"},
        )
    row.used_at = now
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_token", "message": "Invalid or expired verification code"},
        )
    user.email_verified = True
    db.commit()
    return TokenResponse(access_token=create_access_token(user, settings=app_ctx.settings))


@router.post("/auth/resend-verification", status_code=202)
def resend_verification(app_ctx: Ctx, db: DbSession, user: CurrentUser) -> dict:
    if smtp_configured(app_ctx.settings) and not user.email_verified:
        _send_verification_email(db, app_ctx.settings, user)
    return {"status": "accepted"}


@router.post("/auth/login", response_model=TokenResponse)
def login(app_ctx: Ctx, response: Response, payload: LoginRequest, db: DbSession) -> TokenResponse:
    email = payload.email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if (
        user is None
        or not verify_password(payload.password, user.password_hash)
        or not user.email_verified
    ):
        # Unverified accounts get the same generic 401 as bad credentials,
        # but with a machine-readable code so the UI can offer "resend".
        unverified = user is not None and not user.email_verified
        if unverified:
            raise HTTPException(
                status_code=403,
                detail={"code": "email_unverified", "message": "Email verification required"},
            )
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_credentials", "message": "Incorrect email or password"},
        )
    # AUTH-001: MFA-enabled accounts get a purpose-bound step-up token
    # (token_type "mfa", 5 minutes). It is rejected by every normal route;
    # only POST /auth/mfa/challenge accepts it. HTTP 202 signals "accepted,
    # second factor required". Accounts without MFA see zero change.
    if user.totp_secret:
        response.status_code = 202
        mfa_token = create_access_token(
            user, settings=app_ctx.settings, minutes=5, extra_claims={"mfa": True}
        )
        return TokenResponse(access_token=mfa_token, token_type="mfa")
    token = create_access_token(user, settings=app_ctx.settings)
    return TokenResponse(access_token=token, must_change_password=user.must_change_password)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/auth/forgot", status_code=202)
def forgot_password(app_ctx: Ctx, payload: ForgotPasswordRequest, db: DbSession) -> dict:
    """Start a password reset.

    Always returns 202 with a generic body so attackers cannot enumerate
    registered email addresses. Tokens are single-use, expire after
    ``password_reset_token_minutes`` and only their SHA-256 hash is stored.
    """
    email = payload.email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        return {"status": "accepted"}

    now = datetime.now(UTC).replace(tzinfo=None)
    pending = (
        db.execute(
            select(PasswordReset).where(
                PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    for row in pending:
        row.used_at = now

    token = secrets.token_urlsafe(32)
    db.add(
        PasswordReset(
            user_id=user.id,
            token_hash=_hash_reset_token(token),
            expires_at=now + timedelta(minutes=app_ctx.settings.password_reset_token_minutes),
        )
    )
    db.commit()

    delivered = send_mail(
        app_ctx.settings,
        to=user.email,
        subject="পাসওয়ার্ড রিসেট / Password reset",
        body=(f"পাসওয়ার্ড রিসেট করতে নিচের টোকেনটি ব্যবহার করুন (৩০ মিনিটের জন্য বৈধ):\n\n{token}\n"),
    )
    if not delivered:
        if app_ctx.settings.is_production:
            json_log(
                logger,
                logging.WARNING,
                "password_reset_email_undeliverable",
                smtp_configured=smtp_configured(app_ctx.settings),
            )
        else:
            # Non-production convenience: the only place the raw token is
            # ever logged; never emitted when ENV=production.
            json_log(logger, logging.INFO, "password_reset_token_console", token=token)
    return {"status": "accepted"}


@router.post("/auth/reset", response_model=TokenResponse)
def reset_password(app_ctx: Ctx, payload: ResetPasswordRequest, db: DbSession) -> TokenResponse:
    now = datetime.now(UTC).replace(tzinfo=None)
    row = db.execute(
        select(PasswordReset).where(
            PasswordReset.token_hash == _hash_reset_token(payload.token),
            PasswordReset.used_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None or row.expires_at < now:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    row.used_at = now
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    return TokenResponse(access_token=create_access_token(user, settings=app_ctx.settings))


@router.post("/auth/change-password", response_model=TokenResponse)
def change_password(
    app_ctx: Ctx, payload: ChangePasswordRequest, db: DbSession, user: CurrentUser
) -> TokenResponse:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=422, detail="New password must differ from the current one")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    return TokenResponse(access_token=create_access_token(user, settings=app_ctx.settings))


# --- AUTH-001: TOTP multi-factor authentication -------------------------------
# Enroll returns a fresh secret WITHOUT storing it; verify() proves possession
# and stores it (= enabled). Presence of users.totp_secret IS the enabled flag.


@router.post("/auth/mfa/enroll", response_model=MfaEnrollOut)
def mfa_enroll(app_ctx: Ctx, user: CurrentUser) -> MfaEnrollOut:
    secret = new_secret()
    return MfaEnrollOut(secret=secret, otpauth_uri=otpauth_uri(secret, user.email))


@router.post("/auth/mfa/verify", response_model=dict)
def mfa_verify(app_ctx: Ctx, payload: MfaVerifyIn, db: DbSession, user: CurrentUser) -> dict:
    if user.totp_secret:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    if not verify_code(payload.secret, payload.code):
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_mfa_code", "message": "Invalid authenticator code"},
        )
    user.totp_secret = payload.secret
    db.commit()
    return {"enabled": True}


@router.post("/auth/mfa/disable", response_model=dict)
def mfa_disable(app_ctx: Ctx, payload: MfaDisableIn, db: DbSession, user: CurrentUser) -> dict:
    if not user.totp_secret:
        raise HTTPException(status_code=409, detail="MFA is not enabled")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    user.totp_secret = None
    db.commit()
    return {"disabled": True}


@router.post("/auth/mfa/challenge", response_model=TokenResponse)
def mfa_challenge(app_ctx: Ctx, payload: MfaChallengeIn, db: DbSession) -> TokenResponse:
    try:
        claims = decode_token(payload.mfa_token, settings=app_ctx.settings)
        user_id = int(claims["sub"])
    except (pyjwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_mfa_token", "message": "Invalid or expired MFA token"},
        ) from exc
    if claims.get("mfa") is not True:
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_mfa_token", "message": "Not an MFA step-up token"},
        )
    user = db.get(User, user_id)
    if user is None or not user.totp_secret:
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_mfa_token", "message": "Invalid or expired MFA token"},
        )
    if not verify_code(user.totp_secret, payload.code):
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_mfa_code", "message": "Invalid authenticator code"},
        )
    token = create_access_token(user, settings=app_ctx.settings)
    return TokenResponse(access_token=token, must_change_password=user.must_change_password)
