"""System Routes — split from the main.py god-module.

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via:mod:`.deps`, shared helpers via:mod:`.common`.
"""

import logging
import secrets
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import select

from bangla_gpt_api.metrics import (
    REGISTRY,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
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


# AUD-HI-13 (H-02): these four responses used to be declared as an untyped
# free-form object, so a generated client had no schema for them and a rename
# in the handler would have been invisible to the contract. They live here
# rather than in schemas.py (a concurrently-owned module) so the fix stays
# local to the router that serves them.
class HealthOut(BaseModel):
    """Liveness payload: a constant, deliberately without version or env."""

    status: Literal["ok"] = "ok"


class LiveOut(BaseModel):
    """Process-alive payload."""

    status: Literal["alive"] = "alive"


class ReadyOut(BaseModel):
    """Readiness payload: provider name is the only disclosure (no counts)."""

    status: Literal["ready"] = "ready"
    provider: str


class SystemInfoOut(BaseModel):
    """Authenticated build/version identification for operators."""

    status: str
    app: str
    version: str
    env: str


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    # public payload minimal — version/env moved to authenticated endpoint
    return HealthOut()


@router.get("/live", response_model=LiveOut)
async def live() -> LiveOut:
    return LiveOut()


@router.get("/ready", response_model=ReadyOut)
async def ready(app_ctx: Ctx, db: DbSession) -> ReadyOut:
    if app_ctx.provider is None:
        detail = (
            f"LLM_PROVIDER={app_ctx.settings.llm_provider!r} is not implemented yet. "
            "Set LLM_PROVIDER=mock or configure a supported provider."
        )
        raise HTTPException(status_code=503, detail=detail)
    # The retrieval index is what every tutoring turn runs on. A boot whose
    # index failed to build used to answer "ready" while /tutor/ask returned
    # 503 for every student; readiness must state the dependency the product
    # actually needs, so a rolling deploy drains such a worker instead.
    if app_ctx.index is None or app_ctx.tutor is None:
        raise HTTPException(status_code=503, detail="Retrieval index unavailable")
    try:
        db.execute(select(1))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return ReadyOut(provider=app_ctx.provider.name)


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
@router.get("/admin/system/info", responses=AUTH_GUARD_RESPONSES, response_model=SystemInfoOut)
def system_info(app_ctx: Ctx, admin: AdminUser) -> SystemInfoOut:
    return SystemInfoOut(
        status="ok",
        app=app_ctx.settings.app_name,
        version=app_ctx.settings.version,
        env=app_ctx.settings.env,
    )
