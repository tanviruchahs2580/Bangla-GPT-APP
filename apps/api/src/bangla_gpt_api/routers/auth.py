"""Auth Routes — split from the main.py god-module.

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via:mod:`.deps`, shared helpers via:mod:`.common`.
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bangla_gpt_api.auth.mfa import new_secret, otpauth_uri, verify_code
from bangla_gpt_api.auth.security import (
    _burn_password_check,
    create_access_token,
    decode_token,
    hash_password,
    is_common_password,
    needs_rehash,
    verify_password,
)
from bangla_gpt_api.auth.single_use import claim_single_use, fetch_by_hash
from bangla_gpt_api.caching import CacheUnavailable
from bangla_gpt_api.db.models import (
    EmailVerification,
    Parent,
    PasswordReset,
    Student,
    Teacher,
    User,
)
from bangla_gpt_api.logging_config import json_log, json_log_secret
from bangla_gpt_api.routers._error_contract import (
    AUTH_GUARD_RESPONSES,
    coded,
    message,
)
from bangla_gpt_api.routers.deps import AppContext
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
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from bangla_gpt_api.security import encrypt_pii
from bangla_gpt_api.services.mailer import send_mail, smtp_configured
from bangla_gpt_api.services.verification import send_verification_email

from .deps import (
    CONSENT_VERSION,
    BearerCredentials,
    Ctx,
    CurrentUser,
    DbSession,
)

router = APIRouter()

logger = logging.getLogger(__name__)

# --- S-002: per-account failed-login lockout --------------------------------
# The per-IP login rule can be defeated by IP rotation, so the ACCOUNT also
# backs off. Five consecutive password failures lock the account for 60 s;
# every further failure doubles the lock (120 s, 240 s, ... up to 1 hour).
# The counter only resets on a successful sign-in. Kept as module constants
# (not Settings) so no new env surface is introduced.
_LOGIN_LOCKOUT_THRESHOLD = 5
_LOGIN_LOCKOUT_BASE_SECONDS = 60
_LOGIN_LOCKOUT_MAX_SECONDS = 3600
#: Stable machine code for the 429 refusal while locked.
LOGIN_LOCKED_CODE = "account_locked"


@router.post(
    "/auth/register", response_model=RegisterResponse, status_code=201, responses=coded(409)
)
def register(
    app_ctx: Ctx, request: Request, payload: RegisterRequest, db: DbSession
) -> RegisterResponse:
    # Student accounts need a class level and recorded guardian consent. The
    # schema cannot express "required only when role is student", so the rule
    # lives here as a documented 409 (conflict with the account's required
    # state) rather than an undocumented 422 from a model validator (AUD-0053).
    if payload.role == "student":
        if payload.class_level is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "class_level_required",
                    "message": "class_level is required when role is 'student'",
                },
            )
        if not payload.guardian_consent:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "guardian_consent_required",
                    "message": "guardian_consent is required when role is 'student'",
                },
            )
    _reject_common_password(payload.password)
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
            # guardian phone encrypted at rest when PII_ENC_KEY is set.
            phone_enc=encrypt_pii(phone, app_ctx.settings.pii_enc_key),
        )
    else:
        profile = Teacher(name=payload.name.strip(), user_id=user.id)
    db.add(profile)
    db.commit()
    if not verified:
        send_verification_email(db, app_ctx.settings, user)
    return RegisterResponse(user_id=user.id, role=user.role, profile_id=profile.id)


@router.post("/auth/verify-email", response_model=TokenResponse)
def verify_email(app_ctx: Ctx, payload: VerifyEmailRequest, db: DbSession) -> TokenResponse:
    """Complete email verification with the token from the mail.

    On success the account is marked verified and a session is issued.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    # Compare-and-set, not check-then-act: two concurrent requests carrying one
    # verification code must not both redeem it. AUD-0034.
    if not claim_single_use(
        db,
        EmailVerification,
        hash_column=EmailVerification.token_hash,
        hash_value=hashlib.sha256(payload.token.encode()).hexdigest(),
        now=now,
    ):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_token", "message": "Invalid or expired verification code"},
        )
    row = fetch_by_hash(
        db,
        EmailVerification,
        hash_column=EmailVerification.token_hash,
        hash_value=hashlib.sha256(payload.token.encode()).hexdigest(),
    )
    if row is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_token", "message": "Invalid or expired verification code"},
        )
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
def resend_verification(
    app_ctx: Ctx,
    db: DbSession,
    credentials: BearerCredentials,
    payload: ResendVerificationRequest | None = None,
) -> dict:
    """Re-send the email-verification code.

    Reachable both with and without a session: login issues no token
    for unverified accounts, so an authed-only resend left users stuck
    at ``email_unverified`` with a link that always 401'd. When a
    session is present it wins; otherwise ``payload.email`` identifies
    the account. Always answers 202 with a generic body so the endpoint
    cannot be used to enumerate registered addresses.
    """
    target: User | None = None
    if credentials is not None and credentials.scheme.lower() == "bearer":
        try:
            claims = decode_token(credentials.credentials, settings=app_ctx.settings)
            if claims.get("mfa") is not True:
                target = db.get(User, int(claims["sub"]))
        except Exception:
            target = None
    if target is None and payload is not None and payload.email:
        email = payload.email.strip().lower()
        target = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if target is not None and smtp_configured(app_ctx.settings) and not target.email_verified:
        send_verification_email(db, app_ctx.settings, target)
    return {"status": "accepted"}


def _lockout_seconds(failed_count: int) -> int:
    """Progressive lock length: doubles per failure past the threshold."""
    over = max(0, failed_count - _LOGIN_LOCKOUT_THRESHOLD)
    # Explicit int keeps the contract visible (the builtin min() overload with
    # an `int ** int` operand is inferred as Any by this mypy/stubs pair).
    delay: int = _LOGIN_LOCKOUT_BASE_SECONDS * (2**over)
    return min(delay, _LOGIN_LOCKOUT_MAX_SECONDS)


def _lock_remaining_seconds(user: User, now: datetime) -> int | None:
    """Seconds the account stays locked, or None when it is not locked.

    ``users.locked_until`` is a naive UTC column; attach UTC before comparing
    with the timezone-aware ``now`` (SQLite/Postgres both drop tzinfo).
    """
    if user.locked_until is None:
        return None
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    remaining = (locked_until - now).total_seconds()
    if remaining <= 0:
        return None
    return max(1, int(remaining))


@router.post("/auth/login", response_model=TokenResponse, responses=coded(429))
def login(app_ctx: Ctx, response: Response, payload: LoginRequest, db: DbSession) -> TokenResponse:
    email = payload.email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    # F-057, oracle 1 (status code). The old chain short-circuited on
    # `user is None`, so an unknown address and a known-but-unverified one
    # took different branches: 401 vs 403 `email_unverified`. Anyone who
    # guessed ANY password could tell registered addresses apart from
    # unregistered ones and build a list to target with credential stuffing.
    # The unverified hint is now only given once the password is CORRECT --
    # at which point the caller already proves they hold the credential, so
    # the hint discloses nothing they did not already know.
    password_ok = verify_password(payload.password, user.password_hash) if user else False

    # F-057, oracle 2 (timing). Argon2id at 19 MiB / t=2 takes tens of
    # milliseconds. The old code never ran it for an unknown address, so the
    # "no such user" path answered ~5x faster -- an equally reliable oracle
    # that survives any amount of response-body tidying. Do the work either
    # way, against a fixed decoy hash.
    if user is None:
        _burn_password_check(payload.password)
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_credentials", "message": "Incorrect email or password"},
        )

    now = datetime.now(UTC)
    # S-002: while the account is locked, even the CORRECT password is refused
    # (429 + Retry-After), so guessing cannot continue regardless of the
    # caller's IP. The password hash above was still verified, keeping the
    # response time of a locked account in the same band as a normal login.
    lock_remaining = _lock_remaining_seconds(user, now)
    if lock_remaining is not None:
        raise HTTPException(
            status_code=429,
            detail={
                "code": LOGIN_LOCKED_CODE,
                "message": "Account temporarily locked after repeated failed sign-ins",
            },
            headers={"Retry-After": str(lock_remaining)},
        )

    if not password_ok:
        # S-002: count the failure; crossing the threshold stamps a
        # progressive lock. The response body stays exactly the same as for
        # an unknown address (and as before this change).
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= _LOGIN_LOCKOUT_THRESHOLD:
            user.locked_until = now.replace(tzinfo=None) + timedelta(
                seconds=_lockout_seconds(user.failed_login_count)
            )
        db.commit()
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_credentials", "message": "Incorrect email or password"},
        )

    # A successful sign-in clears the account's failure state.
    if (user.failed_login_count or 0) > 0 or user.locked_until is not None:
        user.failed_login_count = 0
        user.locked_until = None
        db.commit()

    if not user.email_verified:
        raise HTTPException(
            status_code=403,
            detail={"code": "email_unverified", "message": "Email verification required"},
        )

    # SEC-02: transparently upgrade the stored hash on a successful login.
    # This runs BEFORE the MFA branch: the old order returned the step-up
    # token first, so a legacy pbkdf2_sha256 hash was never upgraded for any
    # MFA-enabled account, however many times it logged in (F-071).
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        db.commit()

    # AUTH-001: MFA-enabled accounts get a purpose-bound step-up token
    # (token_type "mfa", 5 minutes). It is rejected by every normal route;
    # only POST /auth/mfa/challenge accepts it. HTTP 202 signals "accepted,
    # second factor required". Accounts without MFA see zero change.
    if user.totp_secret:
        response.status_code = 202
        mfa_token = create_access_token(
            user, settings=app_ctx.settings, minutes=5, extra_claims={"mfa": True}
        )
        return TokenResponse(access_token=mfa_token, token_type="mfa")  # noqa: S106 - a token type string, not a credential
    token = create_access_token(user, settings=app_ctx.settings)
    return TokenResponse(access_token=token, must_change_password=user.must_change_password)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


#: Cache key prefix for a consumed MFA step-up token.
_MFA_USED_PREFIX = "mfa_used:"


def _mfa_token_already_used(app_ctx: AppContext, jti: str) -> bool:
    """True when this step-up token has already completed an MFA challenge."""
    try:
        return bool(app_ctx.cache.get_json_strict(f"{_MFA_USED_PREFIX}{jti}"))
    except CacheUnavailable:
        # A cache outage must not turn into a replay. Fail CLOSED, the same
        # rule the impersonation-revocation path uses: an uncheckable
        # credential must not pass.
        return True
    except Exception:
        return True


def _burn_mfa_token(app_ctx: AppContext, jti: str, claims: dict) -> None:
    """Mark a step-up token consumed, for the remainder of its own life."""
    try:
        ttl = float(int(claims.get("exp", 0)) - int(datetime.now(UTC).timestamp()))
    except (TypeError, ValueError):
        ttl = 0.0
    ttl = max(1.0, float(min(ttl, 600.0)))
    try:
        app_ctx.cache.set_json_strict(f"{_MFA_USED_PREFIX}{jti}", 1, ttl)
    except Exception as exc:  # pragma: no cover - defensive
        json_log(logger, logging.WARNING, "mfa_token_burn_failed", error=type(exc).__name__)


def _reject_common_password(password: str) -> None:
    """Refuse a well-known guess with the one coded 400 (F-072).

    Applied at registration, at reset and at change-password. A blocklist on
    registration alone is bypassed the moment a user resets to "12345678",
    which is exactly what a forced-reset flow pushes people toward.
    """
    if is_common_password(password):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "password_too_common",
                "message": "That password is too common. Choose something harder to guess.",
            },
        )


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
            json_log_secret(logger, logging.INFO, "password_reset_token_console", token=token)
    return {"status": "accepted"}


@router.post("/auth/reset", response_model=TokenResponse)
def reset_password(app_ctx: Ctx, payload: ResetPasswordRequest, db: DbSession) -> TokenResponse:
    now = datetime.now(UTC).replace(tzinfo=None)
    # Compare-and-set so a reset token cannot be redeemed twice under
    # concurrency: both a second password write and a token-epoch rotation
    # would otherwise run off the same redeemed token. AUD-0034.
    token_hash = _hash_reset_token(payload.token)
    if not claim_single_use(
        db, PasswordReset, hash_column=PasswordReset.token_hash, hash_value=token_hash, now=now
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    row = fetch_by_hash(
        db, PasswordReset, hash_column=PasswordReset.token_hash, hash_value=token_hash
    )
    if row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    _reject_common_password(payload.new_password)
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    # F-05: rotate the token epoch — every access token issued in an
    # earlier second becomes unusable immediately (get_current_user). The
    # response token is minted naturally; same-second mints stay valid
    # (PyJWT rejects future iat, so the boundary is second-precision).
    user.sessions_invalidated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return TokenResponse(access_token=create_access_token(user, settings=app_ctx.settings))


@router.post(
    "/auth/change-password",
    response_model=TokenResponse,
    responses={**AUTH_GUARD_RESPONSES, **message(400), **coded(409)},
)
def change_password(
    app_ctx: Ctx, payload: ChangePasswordRequest, db: DbSession, user: CurrentUser
) -> TokenResponse:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "password_unchanged",
                "message": "New password must differ from the current one",
            },
        )
    _reject_common_password(payload.new_password)
    now = datetime.now(UTC).replace(tzinfo=None)
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    # F-05: rotate the token epoch (see /auth/reset for the full contract).
    user.sessions_invalidated_at = now
    # S-005: a password change must also kill pending reset tokens. They were
    # left with used_at IS NULL and stayed redeemable for their full TTL, so
    # whoever intercepted a reset link kept a working takeover path for up to
    # password_reset_token_minutes AFTER the victim "fixed" the incident by
    # changing the password. Same transaction: the new hash and the token
    # invalidation commit together or not at all.
    for reset in db.execute(
        select(PasswordReset).where(
            PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
        )
    ).scalars():
        reset.used_at = now
    db.commit()
    return TokenResponse(access_token=create_access_token(user, settings=app_ctx.settings))


# --- AUTH-001: TOTP multi-factor authentication -------------------------------
# Enroll returns a fresh secret WITHOUT storing it; verify proves possession
# and stores it (= enabled). Presence of users.totp_secret IS the enabled flag.


@router.post("/auth/mfa/enroll", response_model=MfaEnrollOut, responses=AUTH_GUARD_RESPONSES)
def mfa_enroll(app_ctx: Ctx, user: CurrentUser) -> MfaEnrollOut:
    secret = new_secret()
    return MfaEnrollOut(secret=secret, otpauth_uri=otpauth_uri(secret, user.email))


@router.post("/auth/mfa/verify", response_model=dict, responses=AUTH_GUARD_RESPONSES)
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


@router.post(
    "/auth/mfa/disable",
    response_model=dict,
    responses={**AUTH_GUARD_RESPONSES, **message(409)},
)
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
    # F-066/F-070: the step-up token was a bearer credential for 5 minutes and
    # could be presented repeatedly. Whoever intercepted one — a proxy log, a
    # shared machine, a shoulder-surfeded phone — got a full login every time
    # they asked, for as long as the authenticator app still showed the same
    # 30-second code. Burn the jti on first successful use.
    jti = claims.get("jti")
    if isinstance(jti, str) and _mfa_token_already_used(app_ctx, jti):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "bad_mfa_token",
                "message": "MFA step-up already completed; log in again",
            },
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
    # Burn the step-up token only AFTER the second factor checks out, so a
    # mistyped code does not cost the user their login.
    if isinstance(jti, str):
        _burn_mfa_token(app_ctx, jti, claims)
    token = create_access_token(user, settings=app_ctx.settings)
    return TokenResponse(access_token=token, must_change_password=user.must_change_password)
