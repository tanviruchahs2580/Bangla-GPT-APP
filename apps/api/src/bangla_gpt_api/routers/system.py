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
from bangla_gpt_api.providers.base import provider_health
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import (
    StatusComponent,
    StatusOut,
)
from bangla_gpt_api.services.circuit_breaker import CircuitState

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
        raise HTTPException(
            status_code=503,
            detail={"code": "provider_misconfigured", "message": detail},
        )
    # The retrieval index is what every tutoring turn runs on. A boot whose
    # index failed to build used to answer "ready" while /tutor/ask returned
    # 503 for every student; readiness must state the dependency the product
    # actually needs, so a rolling deploy drains such a worker instead.
    if app_ctx.index is None or app_ctx.tutor is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "index_unavailable", "message": "Retrieval index unavailable"},
        )
    try:
        db.execute(select(1))
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "database_unavailable", "message": "Database unavailable"},
        ) from exc
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
    # The in-process cache has no "unreachable" state (ping is unconditionally
    # true), so claiming "shared cache reachable" for it would describe a
    # dependency that does not exist. Name the backend that is actually
    # answering (F-123).
    cache_shared = type(app_ctx.cache).__name__ != "MemoryCache"
    if cache_ok:
        cache_detail = "shared cache reachable" if cache_shared else "in-process cache active"
    else:
        cache_detail = "cache unreachable"
    components.append(StatusComponent(name="cache", ok=cache_ok, detail=cache_detail))
    # F-123: "a provider object exists" is not health. Two cheap real signals
    # decide it: the call-outcome tracker (always present -- the live posture
    # sets no fallback provider, so no breaker is built) and the circuit
    # breaker when a fallback chain is configured.
    breaker = app_ctx.circuit_breaker
    breaker_open = breaker is not None and breaker.state is CircuitState.OPEN
    calls_ok, calls_detail = provider_health()
    if app_ctx.provider is None:
        assistant_ok, assistant_detail = False, "no LLM provider configured"
    elif breaker_open:
        assistant_ok, assistant_detail = False, "provider circuit open after repeated failures"
    elif not calls_ok:
        assistant_ok, assistant_detail = False, calls_detail
    else:
        assistant_ok, assistant_detail = True, calls_detail
    components.append(StatusComponent(name="assistant", ok=assistant_ok, detail=assistant_detail))
    # Presence-only, same disclosure rule as the rest of this payload: the
    # status page should show a failed index build (the tutor answers nothing
    # without it) without exposing corpus identity or size.
    index_ok = app_ctx.index is not None and app_ctx.tutor is not None
    components.append(
        StatusComponent(
            name="curriculum",
            ok=index_ok,
            detail="retrieval index loaded" if index_ok else "retrieval index unavailable",
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
            raise HTTPException(
                status_code=403,
                detail={"code": "metrics_denied", "message": "metrics access denied"},
            )
        auth = request.headers.get("authorization", "")
        token = request.headers.get("x-metrics-token", "")
        supplied = [token]
        if auth.lower().startswith("bearer "):
            supplied.append(auth[7:].strip())
        if not any(secrets.compare_digest(s, expected) for s in supplied):
            raise HTTPException(
                status_code=403,
                detail={"code": "metrics_denied", "message": "metrics access denied"},
            )
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


# authenticated internal endpoint with version/env detail (health is now minimal)
@router.get("/admin/system/info", responses=AUTH_GUARD_RESPONSES, response_model=dict)
def system_info(app_ctx: Ctx, admin: AdminUser) -> dict:
    # F-082: the admin surface carries the corpus identity (kind, chunk count,
    # artifact digest, manifest hash) so an answer's stamped digest can be
    # traced to the build that produced it. The public /ready and /status
    # payloads deliberately stay presence-only.
    return {
        "status": "ok",
        "app": app_ctx.settings.app_name,
        "version": app_ctx.settings.version,
        "env": app_ctx.settings.env,
        "corpus": app_ctx.corpus_identity,
    }
