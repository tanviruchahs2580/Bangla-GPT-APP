"""Auth Routes — split from the main.py god-module.

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via:mod:`.deps`, shared helpers via:mod:`.common`.
"""

import hashlib
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select, update
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
from bangla_gpt_api.routers.deps import AppContext, forbid_impersonation
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
from bangla_gpt_api.security import PiiKeyUnconfigured, encrypt_pii_strict
from bangla_gpt_api.services.mailer import send_mail, smtp_configured
from bangla_gpt_api.services.verification import send_verification_email

from .deps import (
    CONSENT_VERSION,
    BearerCredentials,
    Ctx,
    CurrentUser,
    DbSession,
    revocation_store_unavailable,
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

# BE-05: an unauthenticated mail endpooint reachable per-IP at
# 10/min (trivially rotated through a national ISP) is a mail-bomb
# primitive aimed at a guardian inbox. The addresses themselves must be
# the second bound: N mails per account per rolling window, quietly --
# the bodies stay generic either way, so this leaks nothing. Chosen as a
# quota rather than a cooldown on purpose: the documented resend contract
# ("a resend must invalidate the previous code AND re-send immediately")
# is what a student waiting on a lost email is relying on, and a
# cool-down would break it. 5/hour absorbs every legitimate flow (a lost
# first mail, a typo fix, one retry) while capping the bomb.
_MAIL_QUOTA_PER_ADDRESS_PER_HOUR = 5


def _address_mail_quota_allows(app_ctx: Ctx, email: str, kind: str) -> bool:
    """True while ``email`` still has room in its rolling mail window.

    Fail-soft on a backend outage on purpose: a cache that is down must
    not take a public, enumeration-safe endpoint down with it, and the
    per-IP limiter remains the bound in degraded mode (mirrors how the
    MFA throttle degrades).
    """
    key = f"mailq:{kind}:{email.strip().lower()}"
    try:
        count = int(app_ctx.cache.incr(key, ttl=3600.0))
    except CacheUnavailable:
        return True
    except Exception:  # pragma: no cover - defensive, same posture as above
        return True
    return count <= _MAIL_QUOTA_PER_ADDRESS_PER_HOUR


def _encrypt_guardian_phone(app_ctx: Ctx, phone: str | None) -> str | None:
    """Store-side gate for the guardian phone (audit B-04).

    Encryption requires a real decision: a key (``PII_ENC_KEY``) or an
    explicit plaintext consent (``PII_ALLOW_PLAINTEXT``, refused in
    production). A mis-configured deployment fails this one request with a
    coded 503 instead of silently writing a child's guardian contact
    unencrypted.
    """
    try:
        return encrypt_pii_strict(
            phone,
            app_ctx.settings.pii_enc_key,
            allow_plaintext=app_ctx.settings.pii_allow_plaintext,
        )
    except PiiKeyUnconfigured as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "pii_key_unconfigured",
                "message": (
                    "Guardian phone cannot be stored: PII_ENC_KEY is not "
                    "configured and plaintext storage is not allowed"
                ),
            },
        ) from exc


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
            phone_enc=_encrypt_guardian_phone(app_ctx, phone),
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
        if _address_mail_quota_allows(app_ctx, target.email, "verify"):
            send_verification_email(db, app_ctx.settings, target)
        else:
            # Quota: the 202 body is identical either way (enumeration-safe);
            # only the SMTP send is withheld. Logged for ops visibility.
            json_log(logger, logging.WARNING, "mail_quota_exhausted", kind="verify")
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


def _hashed_email(email: str) -> str:
    """Stable pseudonym for a login-failure log line (F-056).

    The raw address is PII and the repo's redaction conventions strip it from
    logs anyway; a truncated SHA-256 lets an operator confirm "this was the
    account I think it was" by hashing a candidate, without the log sink ever
    holding the address itself.
    """
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def _record_failed_login(db: DbSession, user_id: int, now: datetime) -> int:
    """Count one failed sign-in in the database and arm the progressive lock.

    The previous shape was a read-modify-write on the ORM object
    (``user.failed_login_count = (user.failed_login_count or 0) + 1`` then
    commit). Five parallel wrong-password requests all read the counter
    before any of them committed, all wrote the same value, and the lock
    never armed — the account-level control the entire S-002 workstream
    documents was bypassable with five sockets. The increment is now a
    single UPDATE whose right-hand side the database computes, so every
    failure counts exactly once under any interleaving; the RETURNING value
    (SQLite ≥ 3.35 / PostgreSQL) drives the lock stamp in a second
    statement, where a race can only make the stamp *fresher*, never lose
    the count that crossed the threshold.
    """
    new_count = int(
        db.execute(
            update(User)
            .where(User.id == user_id)
            .values(failed_login_count=func.coalesce(User.failed_login_count, 0) + 1)
            .returning(User.failed_login_count)
            .execution_options(synchronize_session=False)
        ).scalar_one()
    )
    if new_count >= _LOGIN_LOCKOUT_THRESHOLD:
        db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                locked_until=now.replace(tzinfo=None)
                + timedelta(seconds=_lockout_seconds(new_count))
            )
            .execution_options(synchronize_session=False)
        )
    db.commit()
    return new_count


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
        # F-056/SEC-15: a failed sign-in against an unknown address wrote no
        # trace at all, so credential stuffing was invisible to operators.
        # Ids/counts/hashes only -- the raw email never reaches the log sink.
        json_log(
            logger,
            logging.WARNING,
            "login_failed",
            reason="unknown_email",
            email_sha256=_hashed_email(email),
        )
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
        json_log(
            logger,
            logging.WARNING,
            "login_refused_locked",
            user_id=user.id,
            retry_after_seconds=lock_remaining,
        )
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
        # an unknown address (and as before this change). The count itself is
        # atomic in the database — see ``_record_failed_login``.
        failed_count = _record_failed_login(db, user.id, now)
        # F-056/SEC-15: the DB counter is reset to 0 by the next successful
        # sign-in, so without a log line a brute force against one account
        # left nothing greppable for detection or incident review.
        json_log(
            logger,
            logging.WARNING,
            "login_failed",
            reason="bad_credentials",
            user_id=user.id,
            failed_count=failed_count,
        )
        if failed_count >= _LOGIN_LOCKOUT_THRESHOLD:
            json_log(
                logger,
                logging.WARNING,
                "account_locked",
                user_id=user.id,
                failed_count=failed_count,
                lock_seconds=_lockout_seconds(failed_count),
            )
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


@router.post("/auth/logout", status_code=204, responses=coded(400))
def logout(app_ctx: Ctx, request: Request, user: CurrentUser) -> None:
    """End THIS session now (S-011).

    The presented token's jti is parked in the fail-closed revocation store
    with a TTL matching the token's remaining life, so it stops
    authenticating immediately instead of living out its 60-minute expiry
    (a password change rotates the epoch for ALL sessions; this is the
    per-session kill switch). Every token carries a jti; one that does not
    is a legacy mint and is refused — silently accepting it would let a
    caller believe a session was ended when it was not.
    """
    claims = getattr(request.state, "jwt_claims", None) or {}
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti:
        raise HTTPException(
            status_code=400,
            detail={"code": "not_revocable", "message": "Token cannot be revoked; log in again"},
        )
    exp = claims.get("exp")
    ttl = max(1.0, float(exp) - time.time()) if isinstance(exp, (int, float)) else 900.0
    # Strict (F-08 discipline): returning 204 while the write failed would
    # claim an end that did not happen.
    try:
        app_ctx.cache.set_json_strict(f"revoke:{jti}", True, ttl)
    except CacheUnavailable as exc:
        raise revocation_store_unavailable() from exc


@router.post("/auth/renew", response_model=TokenResponse, responses=coded(400, 403))
def renew_token(
    app_ctx: Ctx,
    user: CurrentUser,
    credentials: BearerCredentials,
) -> TokenResponse:
    """Slide the session forward: mint a fresh token for the caller (B-02).

    The web client renews PROACTIVELY while the presented token still
    verifies -- a 40-minute class session on one login used to hard-expire
    at minute 60 and bounce the user to /login, losing a quiz in progress.
    An EXPIRED token cannot renew: this is fail-secure by construction (a
    renewal grace window is a replay window; the proactive client contract
    is what keeps honest users out of it). The returned token carries a new
    jti and a full ``jwt_expire_minutes`` from now; the old token dies of
    natural causes at its own expiry and is not force-revoked -- revoking
    it would kill an in-flight request racing this renewal.

    MFA step-up tokens are rejected as API credentials upstream (the
    CurrentUser dependency answers before this runs); impersonation tokens
    must NOT renew -- the 15-minute impersonated window is that design's
    safety bound, so this route refuses them explicitly.
    """
    claims = None
    if credentials is not None and credentials.scheme.lower() == "bearer":
        try:
            claims = decode_token(credentials.credentials, settings=app_ctx.settings)
        except Exception:
            claims = None
    if claims and claims.get("imp"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "renew_unavailable",
                "message": "Impersonation sessions cannot be renewed",
            },
        )
    return TokenResponse(access_token=create_access_token(user, settings=app_ctx.settings))


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


#: Cache key prefix for a consumed MFA step-up token.
_MFA_USED_PREFIX = "mfa_used:"

#: S-012 per-account TOTP throttle: failures counted in a 15-minute window,
#: and the lock that crossing the threshold stamps (also 15 minutes).
_MFA_FAIL_WINDOW_SECONDS = 900
_MFA_FAIL_MAX = 10
_MFA_LOCK_SECONDS = 900


def _mfa_account_locked(app_ctx: AppContext, user_id: int) -> bool:
    """True while the account's MFA challenge is throttled (S-012)."""
    try:
        return app_ctx.cache.get_json(f"mfa_lock:{user_id}") is True
    except CacheUnavailable:
        # Soft by design — see the S-012 note in mfa_challenge.
        return False


def _record_failed_mfa_code(app_ctx: AppContext, user_id: int) -> None:
    """Count one invalid TOTP code; stamp the lock when the window is full.

    The counter moved from a bare ``get_json``/``set_json`` pair to
    ``Cache.incr``: N concurrent guesses (or rotated clients) all read the
    same pre-increment count, all wrote back the same incremented value,
    and the documented 10-failure lock treated the burst as one failure
    (the S-012 guarantee, defeated by exactly the concurrency it existed
    for). The increment is now one atomic operation on both backends.
    """
    key = f"mfa_fail:{user_id}"
    try:
        count = app_ctx.cache.incr(key, _MFA_FAIL_WINDOW_SECONDS)
        if count >= _MFA_FAIL_MAX:
            app_ctx.cache.set_json(f"mfa_lock:{user_id}", True, _MFA_LOCK_SECONDS)
            json_log(logger, logging.WARNING, "mfa_throttle_locked", user_id=user_id)
    except CacheUnavailable:
        pass  # degraded mode: the per-IP rule remains the bound


def _claim_mfa_step_up(app_ctx: AppContext, jti: str, claims: dict) -> bool:
    """Atomically consume a step-up token; False when already consumed.

    The old pair (``get_json_strict`` to check, then ``set_json_strict`` to
    burn) was check-then-act: two concurrent ``/auth/mfa/challenge`` calls
    with the same intercepted token and the same currently-valid 30-second
    code both observed "unused" and both minted full sessions — defeating
    the F-066/F-070 guarantee for exactly the parallel-replay case it was
    written for. The claim is now one SETNX (``Cache.add_if_absent``), so
    exactly one caller wins.

    Backend failure returns False — fail CLOSED, like the check it replaces:
    an uncheckable credential must not pass.
    """
    try:
        ttl = float(int(claims.get("exp", 0)) - int(datetime.now(UTC).timestamp()))
    except (TypeError, ValueError):
        ttl = 0.0
    ttl = max(1.0, float(min(ttl, 600.0)))
    try:
        return bool(app_ctx.cache.add_if_absent(f"{_MFA_USED_PREFIX}{jti}", 1, ttl))
    except CacheUnavailable:
        json_log(logger, logging.WARNING, "mfa_token_claim_unavailable")
        return False
    except Exception as exc:  # pragma: no cover - defensive
        json_log(logger, logging.WARNING, "mfa_token_claim_failed", error=type(exc).__name__)
        return False


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
    if not _address_mail_quota_allows(app_ctx, user.email, "reset"):
        # BE-05 mail quota: identical generic 202 either way (enumeration
        # safety is untouched); tokens and SMTP are both withheld so a
        # bomb attempt cannot churn pending-token rows for the victim.
        json_log(logger, logging.WARNING, "mail_quota_exhausted", kind="reset")
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
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_token", "message": "Invalid or expired reset token"},
        )
    row = fetch_by_hash(
        db, PasswordReset, hash_column=PasswordReset.token_hash, hash_value=token_hash
    )
    if row is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_token", "message": "Invalid or expired reset token"},
        )
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_token", "message": "Invalid or expired reset token"},
        )
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
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_current_password", "message": "Current password is incorrect"},
        )
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
#
# Both state changes are gated twice, and the gates are independent:
#   * never from an impersonated session — the binding OUTLIVES the 15-minute
#     support session that made it, so a visiting admin would leave the
#     account holder needing a code they cannot generate;
#   * never on a bearer token alone — F-142's rule, which /auth/mfa/disable and
#     DELETE /users/me already apply: a security-state change re-supplies the
#     current password. Binding was the one member of that family without it.


@router.post("/auth/mfa/enroll", response_model=MfaEnrollOut, responses=AUTH_GUARD_RESPONSES)
def mfa_enroll(app_ctx: Ctx, user: CurrentUser, request: Request) -> MfaEnrollOut:
    forbid_impersonation(request)
    secret = new_secret()
    return MfaEnrollOut(secret=secret, otpauth_uri=otpauth_uri(secret, user.email))


@router.post("/auth/mfa/verify", response_model=dict, responses=AUTH_GUARD_RESPONSES)
def mfa_verify(
    app_ctx: Ctx, payload: MfaVerifyIn, db: DbSession, user: CurrentUser, request: Request
) -> dict:
    forbid_impersonation(request)
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_current_password", "message": "Current password is incorrect"},
        )
    if user.totp_secret:
        raise HTTPException(
            status_code=409,
            detail={"code": "mfa_already_enabled", "message": "MFA is already enabled"},
        )
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
def mfa_disable(
    app_ctx: Ctx, payload: MfaDisableIn, db: DbSession, user: CurrentUser, request: Request
) -> dict:
    forbid_impersonation(request)
    if not user.totp_secret:
        raise HTTPException(
            status_code=409, detail={"code": "mfa_not_enabled", "message": "MFA is not enabled"}
        )
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_current_password", "message": "Current password is incorrect"},
        )
    user.totp_secret = None
    db.commit()
    return {"disabled": True}


@router.post("/auth/mfa/challenge", response_model=TokenResponse, responses=coded(429))
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
    # shared machine, a shoulder-surfed phone — got a full login every time
    # they asked, for as long as the authenticator app still showed the same
    # 30-second code. The jti is consumed atomically AFTER the second factor
    # checks out (a mistyped code must not cost the user their login), and
    # exactly one concurrent caller can win the claim.
    jti = claims.get("jti")
    user = db.get(User, user_id)
    if user is None or not user.totp_secret:
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_mfa_token", "message": "Invalid or expired MFA token"},
        )
    # S-012: per-ACCOUNT TOTP throttle. The /auth/mfa/challenge rate rule is
    # per-IP, so a botnet could parallelise 6-digit guesses across IPs with
    # no account-level cutoff. Ten failures in the 15-minute window lock
    # this account's MFA challenge for 15 minutes (coded 429, like the
    # S-002 password lockout — not a 401 oracle). Soft on cache outage: the
    # per-IP rule already fails closed upstream on the same backend, so the
    # degraded mode is "IP ceiling only", never "no bound at all".
    if _mfa_account_locked(app_ctx, user_id):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "mfa_locked",
                "message": "Too many invalid codes; try again in a few minutes",
            },
        )
    if not verify_code(user.totp_secret, payload.code):
        _record_failed_mfa_code(app_ctx, user_id)
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_mfa_code", "message": "Invalid authenticator code"},
        )
    # Burn the step-up token only AFTER the second factor checks out, so a
    # mistyped code does not cost the user their login. The claim is atomic:
    # of N concurrent replays of the same token, exactly one proceeds.
    #
    # A token with no jti cannot be claimed, and "cannot be claimed" used to
    # mean "skipped": `isinstance(jti, str) and not _claim(...)` let a
    # jti-less step-up mint real sessions without ever being burned, so the
    # single-use guarantee silently did not apply to it. /auth/logout refuses
    # exactly this shape (400 not_revocable) for the same reason — refusing
    # is the only answer that cannot be believed-and-wrong.
    if not isinstance(jti, str) or not jti or not _claim_mfa_step_up(app_ctx, jti, claims):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "bad_mfa_token",
                "message": "MFA step-up already completed; log in again",
            },
        )
    token = create_access_token(user, settings=app_ctx.settings)
    return TokenResponse(access_token=token, must_change_password=user.must_change_password)
