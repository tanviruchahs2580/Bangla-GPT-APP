"""System Routes — split from the main.py god-module.

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via:mod:`.deps`, shared helpers via:mod:`.common`.
"""

import logging
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select

from bangla_gpt_api.metrics import (
    REGISTRY,
)
from bangla_gpt_api.schemas import (
    StatusComponent,
    StatusOut,
)

from .deps import (
    AdminUser,
    Ctx,
    DbSession,
)

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/health")
async def health() -> dict:
    # public payload minimal — version/env moved to authenticated endpoint
    return {"status": "ok"}


@router.get("/live")
async def live() -> dict:
    return {"status": "alive"}


@router.get("/ready")
async def ready(app_ctx: Ctx, db: DbSession) -> dict:
    if app_ctx.provider is None:
        detail = (
            f"LLM_PROVIDER={app_ctx.settings.llm_provider!r} is not implemented yet. "
            "Set LLM_PROVIDER=mock or configure a supported provider."
        )
        raise HTTPException(status_code=503, detail=detail)
    try:
        db.execute(select(1))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ready", "provider": app_ctx.provider.name}


@router.get("/status", response_model=StatusOut)
def status(app_ctx: Ctx, db: DbSession) -> StatusOut:
    """public status page payload: booleans and presence only --
    no counts of users, no version/env disclosure, nothing an attacker
    or a curious child could profile."""
    components: list[StatusComponent] = []
    try:
        db.execute(select(1))
        components.append(StatusComponent(name="database", ok=True, detail="queries responding"))
    except Exception:
        components.append(StatusComponent(name="database", ok=False, detail="unreachable"))
    try:
        cache_ok = app_ctx.cache.ping()
    except Exception:
        cache_ok = False
    components.append(
        StatusComponent(
            name="cache",
            ok=cache_ok,
            detail="shared cache reachable" if cache_ok else "cache unreachable",
        )
    )
    assistant_ok = app_ctx.provider is not None
    components.append(
        StatusComponent(
            name="assistant",
            ok=assistant_ok,
            detail="provider configured" if assistant_ok else "no LLM provider configured",
        )
    )
    healthy = all(c.ok for c in components)
    return StatusOut(
        status="ok" if healthy else "degraded",
        components=components,
        checked_at=datetime.now(UTC),
    )


@router.get("/metrics", include_in_schema=False)
async def metrics(app_ctx: Ctx, request: Request) -> Response:
    # production gating — token required, via x-metrics-token or Bearer
    if app_ctx.settings.is_production and app_ctx.settings.metrics_require_auth:
        expected = app_ctx.settings.metrics_token or ""
        if not expected:
            # boot guard (enforce_production_safety) refuses this config; the
            # explicit deny keeps /metrics closed if the guard is ever bypassed.
            raise HTTPException(status_code=403, detail="metrics access denied")
        auth = request.headers.get("authorization", "")
        token = request.headers.get("x-metrics-token", "")
        supplied = [token]
        if auth.lower().startswith("bearer "):
            supplied.append(auth[7:].strip())
        if not any(secrets.compare_digest(s, expected) for s in supplied):
            raise HTTPException(status_code=403, detail="metrics access denied")
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


# authenticated internal endpoint with version/env detail (health is now minimal)
@router.get("/admin/system/info", response_model=dict)
def system_info(app_ctx: Ctx, admin: AdminUser) -> dict:
    return {
        "status": "ok",
        "app": app_ctx.settings.app_name,
        "version": app_ctx.settings.version,
        "env": app_ctx.settings.env,
    }
