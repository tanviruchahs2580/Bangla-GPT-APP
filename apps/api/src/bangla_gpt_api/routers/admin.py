"""Admin Routes — split from the main.py god-module (ARCH-001).

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via :mod:`.deps`, shared helpers via :mod:`.common`.
"""

import logging
import secrets
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from bangla_gpt_api.auth.security import (
    create_access_token,
)
from bangla_gpt_api.db.models import (
    AiUsage,
    AuditLog,
    ChatMessage,
    Conversation,
    Feedback,
    QuizAttempt,
    Student,
    User,
)
from bangla_gpt_api.schemas import (
    AdminAiQualityOut,
    AdminAuditPage,
    AdminOverview,
    AdminUsersPage,
    AuditRowOut,
    ImpersonateOut,
    ImpersonateRequest,
    RefusalAuditOut,
    RoleUpdateRequest,
    UserPublic,
)
from bangla_gpt_api.security import write_audit
from bangla_gpt_api.services.retention import run_retention_sweep

from .common import (
    _answer_confidence,
)
from .deps import (
    AdminUser,
    Ctx,
    CurrentUser,
    DbSession,
)

router = APIRouter()

logger = logging.getLogger(__name__)

IMPERSONATION_MINUTES = 15


@router.get("/admin/users", response_model=AdminUsersPage)
def admin_list_users(
    db: DbSession,
    admin: AdminUser,
    q: str | None = Query(default=None, max_length=120),
    role: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminUsersPage:
    """Paginated, searchable user list (C18)."""
    statement = select(User)
    count_stmt = select(func.count()).select_from(User)
    if q:
        like = f"%{q.strip().lower()}%"
        statement = statement.where(func.lower(User.email).like(like))
        count_stmt = count_stmt.where(func.lower(User.email).like(like))
    if role:
        statement = statement.where(User.role == role)
        count_stmt = count_stmt.where(User.role == role)
    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(statement.order_by(User.id).offset(offset).limit(limit)).scalars().all()
    return AdminUsersPage(
        total=total,
        items=[
            UserPublic(id=u.id, email=u.email, role=u.role, created_at=u.created_at) for u in rows
        ],
    )


@router.patch("/admin/users/{user_id}/role", response_model=UserPublic)
def admin_update_role(
    user_id: int, payload: RoleUpdateRequest, db: DbSession, admin: AdminUser
) -> UserPublic:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "admin" and payload.role != "admin":
        admins = db.execute(
            select(func.count()).select_from(User).where(User.role == "admin")
        ).scalar_one()
        if admins <= 1:
            raise HTTPException(status_code=409, detail="Cannot demote the last admin")
    old_role = target.role
    target.role = payload.role
    # S5.6 audit event 1/5: role_change (ids + before/after only)
    write_audit(
        db,
        action="role_change",
        actor_user_id=admin.id,
        actor_role=admin.role,
        target=f"user:{target.id}",
        detail={"from": old_role, "to": payload.role},
    )
    db.commit()
    db.refresh(target)
    return UserPublic(
        id=target.id, email=target.email, role=target.role, created_at=target.created_at
    )


# --- S5.6: audited support impersonation (audit event 5/5) ---
# Short-lived token for the target user, minted only by an admin, with
# start AND stop rows in the audit trail. Admin-role targets are refused:
# support never needs admin powers. S5.10 added the missing piece: the
# token carries a jti and POST /auth/impersonate/exit revokes it through
# the shared cache, so a session no longer rides out its 15-minute ceiling.


@router.post("/admin/users/{user_id}/impersonate", response_model=ImpersonateOut)
def admin_impersonate(
    app_ctx: Ctx, user_id: int, payload: ImpersonateRequest, db: DbSession, admin: AdminUser
) -> ImpersonateOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role in ("admin", "school_admin"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "impersonation_forbidden",
                "message": "admins cannot be impersonated",
            },
        )
    jti = secrets.token_hex(16)
    token = create_access_token(
        target,
        settings=app_ctx.settings,
        minutes=IMPERSONATION_MINUTES,
        # jti makes this specific token revocable (S5.10 exit button /
        # admin revoke), which stateless JWT alone cannot do.
        jti=jti,
        extra_claims={"imp": True, "imp_by": admin.id},
    )
    # F-SEC-01: index active JTIs per target so admin revoke can find them
    try:
        existing = app_ctx.cache.get_json(f"imp_active:{target.id}") or []
        if not isinstance(existing, list):
            existing = []
        existing.append(jti)
        # keep only recent 10 to bound memory
        existing = existing[-10:]
        app_ctx.cache.set_json(f"imp_active:{target.id}", existing, ttl=IMPERSONATION_MINUTES * 60)
    except Exception:
        pass
    write_audit(
        db,
        action="impersonation",
        actor_user_id=admin.id,
        actor_role=admin.role,
        target=f"user:{target.id}",
        detail={"phase": "start", "reason": payload.reason, "minutes": IMPERSONATION_MINUTES},
    )
    db.commit()
    return ImpersonateOut(
        access_token=token,
        user_id=target.id,
        role=target.role,
        expires_in_min=IMPERSONATION_MINUTES,
    )


@router.delete("/admin/users/{user_id}/impersonate", status_code=204)
def admin_impersonate_end(app_ctx: Ctx, user_id: int, db: DbSession, admin: AdminUser) -> None:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    # F-SEC-01: revoke all active impersonation JTIs for this target
    try:
        active = app_ctx.cache.get_json(f"imp_active:{target.id}") or []
        if isinstance(active, list):
            for j in active:
                if isinstance(j, str) and j:
                    app_ctx.cache.set_json(f"imp_revoke:{j}", True, ttl=IMPERSONATION_MINUTES * 60)
        # clear the active index
        app_ctx.cache.set_json(f"imp_active:{target.id}", [], ttl=1)
    except Exception:
        pass
    write_audit(
        db,
        action="impersonation",
        actor_user_id=admin.id,
        actor_role=admin.role,
        target=f"user:{target.id}",
        detail={"phase": "stop"},
    )
    db.commit()


@router.post("/auth/impersonate/exit", status_code=204)
def impersonate_exit(app_ctx: Ctx, request: Request, db: DbSession, user: CurrentUser) -> None:
    """S5.10: the holder of an impersonation token ends the session NOW.

    The jti lands in the revocation cache with a TTL equal to the token's
    remaining life, so the token stops working at once and the cache entry
    itself disappears when the token would have expired anyway. Only works
    with an impersonation token -- a normal session token cannot 'exit'
    itself into 401s (that would be a self-DoS foot-gun).
    """
    claims = getattr(request.state, "jwt_claims", None) or {}
    if not claims.get("imp") or not isinstance(claims.get("jti"), str):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "not_impersonation",
                "message": "only an impersonation session can exit here",
            },
        )
    exp = claims.get("exp")
    ttl = max(1.0, float(exp) - time.time()) if isinstance(exp, (int, float)) else 900.0
    app_ctx.cache.set_json(f"imp_revoke:{claims['jti']}", True, ttl)
    write_audit(
        db,
        action="impersonation",
        actor_user_id=user.id,
        actor_role=user.role,
        target=f"user:{user.id}",
        detail={"phase": "exit", "imp_by": claims.get("imp_by")},
    )
    db.commit()


@router.get("/admin/audit", response_model=AdminAuditPage)
def admin_audit(
    db: DbSession,
    admin: AdminUser,
    action: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminAuditPage:
    """S5.6: the privileged-action trail (newest first), admin-only."""
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    count_stmt = select(func.count()).select_from(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(stmt.offset(offset).limit(limit)).scalars().all()
    return AdminAuditPage(
        rows=[
            AuditRowOut(
                id=r.id,
                created_at=r.created_at,
                actor_user_id=r.actor_user_id,
                actor_role=r.actor_role,
                action=r.action,
                target=r.target,
                detail=dict(r.detail),
            )
            for r in rows
        ],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/admin/analytics/overview", response_model=AdminOverview)
def admin_overview(db: DbSession, admin: AdminUser) -> AdminOverview:
    # F-PERF-04: SQL aggregates instead of full-history Python loops
    users_total = db.execute(select(func.count()).select_from(User)).scalar_one()
    by_role_rows = db.execute(select(User.role, func.count()).group_by(User.role)).all()
    by_role = {r: int(c) for r, c in by_role_rows}
    graded_count, avg_score_raw = db.execute(
        select(func.count(), func.avg(QuizAttempt.score_pct)).where(
            QuizAttempt.status == "graded", QuizAttempt.score_pct.is_not(None)
        )
    ).one()
    return AdminOverview(
        users_total=int(users_total),
        students=by_role.get("student", 0),
        teachers=by_role.get("teacher", 0),
        admins=by_role.get("admin", 0),
        parents=by_role.get("parent", 0),
        quiz_attempts_graded=int(graded_count),
        avg_score_pct=round(float(avg_score_raw), 2) if avg_score_raw is not None else None,
    )


@router.get("/admin/safety/refusals", response_model=RefusalAuditOut)
def admin_refusal_audit(db: DbSession, admin: AdminUser, days: int = 30) -> RefusalAuditOut:
    """S4.8 refusal audit: why and where safety refusals happened.

    Aggregates the refused_reason already persisted on ChatMessage --
    counts only, never message content (R11 child-data minimization).
    """
    days = max(1, min(days, 365))
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    rows = db.execute(
        select(ChatMessage.refused_reason, Student.class_level, ChatMessage.created_at)
        .join(Conversation, ChatMessage.conversation_id == Conversation.id)
        .join(Student, Conversation.student_id == Student.id)
        .where(ChatMessage.refused_reason.is_not(None))
        .where(ChatMessage.created_at >= cutoff)
    ).all()
    by_reason: dict[str, int] = defaultdict(int)
    by_class: dict[str, int] = defaultdict(int)
    last_at: datetime | None = None
    for reason, class_level, created_at in rows:
        by_reason[reason or "unknown"] += 1
        by_class[str(class_level)] += 1
        if last_at is None or created_at > last_at:
            last_at = created_at
    return RefusalAuditOut(
        days=days,
        total_refusals=len(rows),
        by_reason=dict(by_reason),
        by_class=dict(by_class),
        last_refusal_at=last_at,
    )


@router.get("/admin/ai/quality", response_model=AdminAiQualityOut)
def admin_ai_quality(
    db: DbSession,
    admin: AdminUser,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AdminAiQualityOut:
    """Wave 2 AI-quality dashboard: last-N-days answer quality COUNTS only
    -- refusals by reason, thumbs, grounding split and the share of
    low-confidence answers under the documented confidence formula.

    Audit finding reflected in the payload: ChatMessage has no model
    column, so ``by_model`` is honestly empty today (no fabricated split).
    """
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    rows = db.execute(
        select(ChatMessage.grounded, ChatMessage.refused_reason, ChatMessage.sources_json).where(
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= cutoff,
        )
    ).all()
    by_reason: dict[str, int] = defaultdict(int)
    grounded_count = 0
    ungrounded_count = 0
    low_confidence = 0
    for grounded, reason, sources_json in rows:
        if reason:
            by_reason[reason] += 1
        if grounded is True:
            grounded_count += 1
        elif grounded is False:
            # None (pre-grounding rows) is counted in answers_total only --
            # it is neither grounded nor ungrounded, and we do not guess.
            ungrounded_count += 1
        scores = [float(s.get("score", 0.0)) for s in (sources_json or [])]
        confidence = _answer_confidence(grounded, reason, scores)
        if confidence is not None and confidence < 0.5:
            low_confidence += 1
    thumbs = db.execute(
        select(Feedback.rating, func.count())
        .where(Feedback.created_at >= cutoff, Feedback.message_id.is_not(None))
        .group_by(Feedback.rating)
    ).all()
    thumbs_up = sum(int(n) for rating, n in thumbs if rating == 1)
    thumbs_down = sum(int(n) for rating, n in thumbs if rating == -1)
    # AI-002: estimated spend over the same window, from the usage ledger.
    cost_rows = db.execute(
        select(AiUsage.model, func.sum(AiUsage.estimated_cost_usd))
        .where(AiUsage.created_at >= cutoff)
        .group_by(AiUsage.model)
    ).all()
    cost_by_model = {str(model): round(float(total or 0.0), 6) for model, total in cost_rows}
    return AdminAiQualityOut(
        days=days,
        answers_total=len(rows),
        grounded_count=grounded_count,
        ungrounded_count=ungrounded_count,
        refusals_total=sum(by_reason.values()),
        refusals_by_reason=dict(by_reason),
        thumbs_up=thumbs_up,
        thumbs_down=thumbs_down,
        low_confidence_count=low_confidence,
        by_model={},
        cost_usd_total=round(sum(cost_by_model.values()), 6),
        cost_usd_by_model=cost_by_model,
    )


@router.post("/admin/maintenance/purge", response_model=dict)
def admin_purge_expired(
    app_ctx: Ctx, db: DbSession, admin: AdminUser, dry_run: bool = False
) -> dict:
    """Retention sweep (D20, S5.8): expired tokens, stale invites, old chats.

    Child-data minimization: conversations older than
    ``chat_retention_days`` are deleted with their messages. With
    ``dry_run=true`` the SAME count report is returned without deleting
    anything (compliance evidence); real runs also write the audit row.
    """
    report = run_retention_sweep(db, settings=app_ctx.settings, dry_run=dry_run)
    if not dry_run:
        # S5.6 audit event 3/5: purge (counts only -- never deleted content)
        write_audit(
            db,
            action="purge",
            actor_user_id=admin.id,
            actor_role=admin.role,
            target="retention_sweep",
            detail={k: v for k, v in report.items() if k != "dry_run"},
        )
        db.commit()
    return report
