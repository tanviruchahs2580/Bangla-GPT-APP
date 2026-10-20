"""Auth session routes — login, rotation and logout (C-03 split).

Extracted verbatim from ``routers/auth.py`` (the audit's god-module list) so
each file stays under the file-size ratchet. Behaviour-identical: same paths,
same validation, same status codes, and the same *registration order* —
``auth.py`` includes this router exactly where the three handlers used to be
defined (register/verify-email/resend-verification -- login/refresh/logout --
forgot/reset/change-password/mfa), so the served route table and the OpenAPI
document are unchanged.

Shared seams: ``_issue_session``/``SessionTokenResponse`` live here (the
login response shape) and are re-used by the verification, reset, change
and MFA handlers that stayed in ``auth.py``. The refresh-rotation helpers
implement B-02 (single-use jti claims, family revocation on replay); the
lockout helpers implement S-002 (progressive per-account lockout).
"""

import calendar
import logging
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import select

from bangla_gpt_api.auth.security import (
    REFRESH_TOKEN_TYP,
    _burn_password_check,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from bangla_gpt_api.caching import CacheUnavailable
from bangla_gpt_api.db.models import User
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.routers._error_contract import (
    AUTH_GUARD_RESPONSES,
    coded,
)
from bangla_gpt_api.routers.deps import (
    AppContext,
    Ctx,
    CurrentUser,
    DbSession,
    revocation_store_unavailable,
)
from bangla_gpt_api.schemas import (
    LoginRequest,
    StrictIn,
    TokenResponse,
)

router = APIRouter()

logger = logging.getLogger(__name__)


# --- B-02: rotating refresh tokens -------------------------------------------
class SessionTokenResponse(TokenResponse):
    """A full login response: access token + its rotating refresh successor.

    Extra optional fields rather than a new response model for the wide
    routes, so an old client that only reads ``access_token`` is unaffected;
    a new client renews with ``refresh_token`` at POST /auth/refresh instead
    of holding a long-lived access token.
    """

    refresh_token: str | None = None
    expires_in: int | None = None  # access-token lifetime in seconds


class RefreshRequest(StrictIn):
    refresh_token: str = Field(min_length=10, max_length=4096)


class LogoutRequest(StrictIn):
    # Optional: a client that only holds an access token still logs out the
    # way it always did; one that holds the refresh token hands it back so
    # the session cannot be resumed from it either.
    refresh_token: str | None = Field(default=None, max_length=4096)


def _issue_session(
    app_ctx: AppContext, user: User, *, family: str | None = None
) -> SessionTokenResponse:
    """Mint an access token and a fresh refresh token for one session.

    The refresh family is preserved across rotations so replay detection can
    revoke a whole login lineage; a new login starts a new family.
    """
    access = create_access_token(user, settings=app_ctx.settings)
    refresh = create_refresh_token(user, settings=app_ctx.settings, family=family)
    return SessionTokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=app_ctx.settings.jwt_expire_minutes * 60,
        must_change_password=user.must_change_password,
    )


#: Cache key prefixes for refresh-token rotation (B-02): a single-use claim
#: per rotated jti, and a family revocation marker written when a rotated
#: token is replayed (theft detection).
_REFRESH_USED_PREFIX = "refresh_used:"
_REFRESH_FAMILY_REVOKE_PREFIX = "refresh_fam_revoke:"

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


def _register_login_failure(db: DbSession, user: User, now: datetime) -> None:
    """S-002: count the failure; crossing the threshold stamps a progressive
    lock. The response body stays exactly the same as for an unknown address."""
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= _LOGIN_LOCKOUT_THRESHOLD:
        user.locked_until = now.replace(tzinfo=None) + timedelta(
            seconds=_lockout_seconds(user.failed_login_count)
        )
    db.commit()


def _clear_login_failure(db: DbSession, user: User) -> None:
    if (user.failed_login_count or 0) > 0 or user.locked_until is not None:
        user.failed_login_count = 0
        user.locked_until = None
        db.commit()


@router.post("/auth/login", response_model=SessionTokenResponse, responses=coded(401, 403, 429))
def login(
    app_ctx: Ctx, response: Response, payload: LoginRequest, db: DbSession
) -> SessionTokenResponse:
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
        _register_login_failure(db, user, now)
        raise HTTPException(
            status_code=401,
            detail={"code": "bad_credentials", "message": "Incorrect email or password"},
        )

    # A successful sign-in clears the account's failure state.
    _clear_login_failure(db, user)

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
        return SessionTokenResponse(access_token=mfa_token, token_type="mfa")  # noqa: S106 - a token type string, not a credential
    return _issue_session(app_ctx, user)


#: Cache-key prefix for tokens retired by logout (AUD-B-04). The shared store
#: is the one the impersonation deny-list already uses; the TTL is the token's
#: own remaining life, so the keyspace prunes itself.
_REVOKED_JTI_KEY_PREFIX = "token_revoke:"


@router.post("/auth/refresh", response_model=SessionTokenResponse, responses={**coded(401, 503)})
def refresh_session(app_ctx: Ctx, payload: RefreshRequest, db: DbSession) -> SessionTokenResponse:
    """Rotate a refresh token into a new access token (B-02).

    Security properties, in the order they are checked:

    1. signature/iss/aud/expiry via ``decode_token`` and a ``typ=refresh``
       check -- an access token cannot be replayed here, and a refresh token
       cannot be used anywhere else (``get_current_user`` refuses it);
    2. the login family is not revoked (a replay revoked it earlier);
    3. the presented token was not already rotated -- the claim is one atomic
       ``SET NX`` in the shared store, so two concurrent refreshes with one
       token produce exactly one successor;
    4. the account still exists, is verified, and the token is not older than
       ``sessions_invalidated_at`` (password change/reset kills refresh tokens
       the same second-precision way it kills access tokens).

    A token that fails (3) is the classic stolen-refresh-token signal: the
    whole family is revoked and 401 is returned, so neither the thief nor the
    victim keeps a usable session -- a fresh login is the only way back in.
    When the shared store is unreachable, rotation fails CLOSED with 503
    (``revocation_unavailable``): an unverifiable claim cannot be recorded,
    so issuing a successor would silently break replay detection.
    """
    claims = _refresh_claims(payload.refresh_token, app_ctx.settings)
    jti = str(claims["jti"])
    family = str(claims["fam"])
    user_id = int(claims["sub"])
    _claim_rotation(app_ctx, claims, jti=jti, family=family)
    user = db.get(User, user_id)
    if user is None or not user.email_verified:
        raise _bad_refresh()
    # F-05 token epoch, applied to refresh tokens too: a password change or
    # reset must kill outstanding refresh tokens, else the leaked credential
    # outlives the incident by up to jwt_refresh_expire_days.
    if not _issued_after_epoch(user, claims):
        raise _bad_refresh()
    return _issue_session(app_ctx, user, family=family)


def _refresh_claims(refresh_token: str, settings) -> dict:  # noqa: ANN001 - Settings
    """Decode and structurally validate a refresh token (steps 1 and 4a)."""
    try:
        claims = decode_token(refresh_token, settings=settings)
    except pyjwt.PyJWTError as exc:
        raise _bad_refresh() from exc
    if claims.get("typ") != REFRESH_TOKEN_TYP:
        raise _bad_refresh()
    jti = claims.get("jti")
    family = claims.get("fam")
    if not isinstance(jti, str) or not jti or not isinstance(family, str) or not family:
        raise _bad_refresh()
    try:
        int(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _bad_refresh() from exc
    return claims


def _claim_rotation(app_ctx: Ctx, claims: dict, *, jti: str, family: str) -> None:
    """Revocation checks plus the atomic single-use claim (steps 2 and 3).

    A failed claim is the stolen-refresh-token signal: the family is revoked
    loudly and 401 returned. An unreachable store fails CLOSED with 503 -- an
    unverifiable claim cannot be recorded, so issuing a successor would
    silently break replay detection.
    """
    try:
        if app_ctx.cache.get_json_strict(_REFRESH_FAMILY_REVOKE_PREFIX + family) is True:
            raise _bad_refresh()
        # Logout writes the presented token's jti here (same deny-list the
        # access token uses), so a logged-out refresh token is refused.
        if app_ctx.cache.get_json_strict(f"{_REVOKED_JTI_KEY_PREFIX}{jti}") is True:
            raise _bad_refresh()
        try:
            remaining = max(1, int(claims.get("exp", 0)) - int(datetime.now(UTC).timestamp()))
        except (TypeError, ValueError):
            remaining = app_ctx.settings.jwt_refresh_expire_days * 86400
        if not app_ctx.cache.set_json_nx_strict(_REFRESH_USED_PREFIX + jti, True, remaining):
            # Replay of an already-rotated token: revoke the family loudly.
            app_ctx.cache.set_json_strict(
                _REFRESH_FAMILY_REVOKE_PREFIX + family,
                True,
                app_ctx.settings.jwt_refresh_expire_days * 86400,
            )
            json_log(logger, logging.WARNING, "refresh_token_replay_detected", family_revoked=True)
            raise _bad_refresh()
    except CacheUnavailable as exc:
        raise revocation_store_unavailable() from exc


def _issued_after_epoch(user: User, claims: dict) -> bool:
    """True when the token was issued after the account's invalidation stamp."""
    invalidated = user.sessions_invalidated_at
    if invalidated is None:
        return True
    inv_ts = (
        calendar.timegm(invalidated.timetuple())
        if invalidated.tzinfo is None
        else int(invalidated.timestamp())
    )
    iat = claims.get("iat")
    return isinstance(iat, int) and iat >= inv_ts


def _bad_refresh() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "bad_refresh_token", "message": "Invalid or expired refresh token"},
    )


@router.post("/auth/logout", status_code=204, responses={**AUTH_GUARD_RESPONSES, **coded(503)})
def logout(
    app_ctx: Ctx,
    request: Request,
    user: CurrentUser,
    payload: LogoutRequest | None = None,
) -> Response:
    """Retire the caller's token server-side (AUD-B-04).

    Clearing client storage is not revocation: the bearer token stays valid
    until ``exp`` (60 minutes by default), so a copy taken off the device
    keeps working after a "logout". This endpoint writes the token's ``jti``
    into the shared deny-list that ``get_current_user`` consults, for exactly
    the token's remaining life.

    The write is strict (same posture as impersonation revocation): when the
    store is unreachable the caller gets 503 instead of a false "logged out".
    A client should clear its local state either way -- the response is the
    server-side half of the decision.
    """
    claims = getattr(request.state, "jwt_claims", None) or {}
    jti = claims.get("jti")
    if isinstance(jti, str) and jti:
        _revoke_jti(app_ctx, jti, claims, ttl_fallback=app_ctx.settings.jwt_expire_minutes * 60)
    # B-02: a client that holds the refresh token returns it here, so the
    # session cannot be resumed from it either. Best-effort validation: a
    # malformed token is ignored (the access-token revocation above already
    # landed), and only a VALID token's jti names a key that could matter.
    if payload is not None and payload.refresh_token:
        _retire_presented_refresh_token(app_ctx, payload.refresh_token, claims)
    # Structured, id-free: the deny-list entry already records the decision,
    # and a raw user id in a log line is exactly what AUD-HI-18 is removing.
    json_log(logger, logging.INFO, "logout_token_revoked", jti=jti is not None)
    return Response(status_code=204)


def _revoke_jti(app_ctx: Ctx, jti: str, claims: dict, *, ttl_fallback: int) -> None:
    """Deny-list one jti for its remaining life (strict: 503 when unreachable)."""
    try:
        remaining = int(claims.get("exp", 0)) - int(datetime.now(UTC).timestamp())
    except (TypeError, ValueError):
        remaining = ttl_fallback
    try:
        app_ctx.cache.set_json_strict(_REVOKED_JTI_KEY_PREFIX + jti, True, max(1, remaining))
    except CacheUnavailable as exc:
        raise revocation_store_unavailable() from exc


def _retire_presented_refresh_token(app_ctx: Ctx, refresh_token: str, claims: dict) -> None:
    """Deny-list a valid, same-subject refresh token presented at logout."""
    try:
        refresh_claims = decode_token(refresh_token, settings=app_ctx.settings)
    except pyjwt.PyJWTError:
        return
    refresh_jti = refresh_claims.get("jti")
    if (
        refresh_claims.get("typ") != REFRESH_TOKEN_TYP
        or str(refresh_claims.get("sub")) != str(claims.get("sub"))
        or not isinstance(refresh_jti, str)
        or not refresh_jti
    ):
        return
    _revoke_jti(
        app_ctx,
        refresh_jti,
        refresh_claims,
        ttl_fallback=app_ctx.settings.jwt_refresh_expire_days * 86400,
    )
    json_log(logger, logging.INFO, "logout_refresh_token_revoked")
