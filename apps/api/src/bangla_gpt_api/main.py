"""Bangla GPT API — application bootstrap (slim entrypoint).

All domain routes live in :mod:`bangla_gpt_api.routers` (ARCH-001 split);
this module keeps only boot concerns: settings, observability, dependency
construction, middleware, lifespan and the gunicorn ``app``.

The monolithic ``main.py`` (previously ~7000 lines) has been refactored into:

- ``initialize/observability``   : logging + Sentry bootstrap
- ``initialize/middleware_stack`` : all middleware registration
- ``initialize/dependencies``    : index/DB/admin construction (providers passed in)
- ``initialize/lifespan``        : lifespan context with explicit params
- ``initialize/schedulers``      : background scheduler loops with health monitoring

All these modules are imported from :mod:`bangla_gpt_api.initialize`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bangla_gpt_api import caching, initialize
from bangla_gpt_api.config import DEFAULT_JWT_SECRET, Settings, get_settings

if TYPE_CHECKING:  # typing-only: never executed, so no import cycles
    from bangla_gpt_api.providers.base import LLMProvider

# Re-exports for backward-compatibility: tests monkeypatch main.get_provider,
# main.get_fast_provider, main.HybridIndex, main.make_engine, main.TutorService,
# main.build_limiter directly.
from bangla_gpt_api.db.session import make_engine  # noqa: F401 (re-exported for tests)
from bangla_gpt_api.initialize.dependencies import (
    build_dependencies,
)
from bangla_gpt_api.initialize.middleware_stack import build_middleware_stack
from bangla_gpt_api.initialize.observability import (
    configure_observability_with_sentry,
)
from bangla_gpt_api.providers import (
    ProviderNotConfigured,  # noqa: F401 (re-exported for tests)
    get_fast_provider,  # noqa: F401 (re-exported for tests)
    get_provider,  # noqa: F401 (re-exported for tests)
)
from bangla_gpt_api.ratelimit import build_limiter  # noqa: F401 (re-exported for tests)
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex  # noqa: F401 (re-exported for tests)
from bangla_gpt_api.routers import register_routers
from bangla_gpt_api.routers.deps import CONSENT_VERSION
from bangla_gpt_api.services.circuit_breaker import CircuitBreaker  # noqa: F401
from bangla_gpt_api.services.tutor import TutorService  # noqa: F401 (re-exported for tests)

__all__ = ["CONSENT_VERSION", "app", "create_app", "enforce_production_safety"]
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Production safety validators (separate from create_app for SRP)
# ---------------------------------------------------------------------------


def enforce_production_safety(settings: Settings) -> None:
    """Refuse to boot in production with insecure configuration (B6).

    Each check is a standalone validator function (SRP).  When any check
    fails, the combined error is raised as a single RuntimeError.
    """
    if not settings.is_production:
        return

    problems: list[str] = []

    for validator in (
        _validate_smtp,
        _validate_jwt,
        _validate_admin,
        _validate_cors,
        _validate_database,
        _validate_pii,
        _validate_metrics,
        _validate_rate_limit_redis,
        _validate_llm_provider,
    ):
        try:
            problems.extend(validator(settings))
        except Exception:
            problems.append(f"Configuration check failed: {validator.__name__}")

    if problems:
        raise RuntimeError(
            "Refusing to start: insecure production configuration detected:\n- "
            + "\n- ".join(problems)
        )


def _validate_smtp(settings: Settings) -> list[str]:
    """SMTP must be configured in production, else email verification is bypassed (F-SEC-03)."""
    try:
        from bangla_gpt_api.services.mailer import smtp_configured

        if not smtp_configured(settings):
            return [
                "SMTP must be configured in production "
                "(SMTP_ENABLED=true, SMTP_HOST and SMTP_FROM) — "
                "otherwise email verification is bypassed"
            ]
    except ModuleNotFoundError:
        return ["mailer service not installed — cannot verify SMTP configuration"]
    except Exception:
        return ["SMTP configuration check failed"]
    return []


def _validate_jwt(settings: Settings) -> list[str]:
    """JWT_SECRET must be overridden in production with at least 32 random characters."""
    if settings.jwt_secret == DEFAULT_JWT_SECRET or len(settings.jwt_secret) < 32:
        return ["JWT_SECRET must be overridden in production with at least 32 random characters"]
    return []


def _validate_admin(settings: Settings) -> list[str]:
    """Admin credentials must be configured and strong in production."""
    problems: list[str] = []
    if not settings.admin_email or not settings.admin_password:
        problems.append("ADMIN_EMAIL and ADMIN_PASSWORD must be configured in production")
    elif len(settings.admin_password) < 12:
        problems.append("ADMIN_PASSWORD must be at least 12 characters in production")
    return problems


def _validate_cors(settings: Settings) -> list[str]:
    """CORS origins must be explicitly set in production; no wildcards."""
    if not settings.allowed_origins.strip():
        return ["ALLOWED_ORIGINS must be set in production (comma-separated allowlist)"]
    if "*" in settings.allowed_origins:
        return ["ALLOWED_ORIGINS must not contain wildcard '*' in production"]
    return []


def _validate_database(settings: Settings) -> list[str]:
    """DATABASE_URL must be a persistent store in production."""
    if settings.database_url.strip() == "sqlite://":
        return [
            "DATABASE_URL must be a persistent store in production "
            "(e.g. sqlite:////data/app.db or PostgreSQL)"
        ]
    return []


def _validate_pii(settings: Settings) -> list[str]:
    """PII_ENC_KEY must be set in production (guardian phone encryption)."""
    if not settings.pii_enc_key:
        return ["PII_ENC_KEY must be set in production (guardian phone encryption)"]
    return []


def _validate_metrics(settings: Settings) -> list[str]:
    """METRICS_REQUIRE_AUTH must be true and METRICS_TOKEN must be set."""
    problems: list[str] = []
    if not settings.metrics_require_auth:
        problems.append(
            "METRICS_REQUIRE_AUTH must be true in production (/metrics must not be public)"
        )
    elif not settings.metrics_token:
        problems.append("METRICS_TOKEN must be set in production when METRICS_REQUIRE_AUTH=true")
    return problems


def _validate_rate_limit_redis(settings: Settings) -> list[str]:
    """Redis rate-limit backend requires REDIS_URL."""
    if settings.rate_limit_backend == "redis" and not settings.redis_url:
        return ["RATE_LIMIT_BACKEND=redis requires REDIS_URL"]
    return []


def _validate_llm_provider(settings: Settings) -> list[str]:
    """Gemini provider requires GEMINI_API_KEY in production."""
    if settings.llm_provider.strip().lower() == "gemini" and not settings.gemini_api_key:
        return ["LLM_PROVIDER=gemini requires GEMINI_API_KEY in production"]
    return []


# ---------------------------------------------------------------------------
# Provider construction helpers (called from create_app so tests can monkeypatch)
# ---------------------------------------------------------------------------


def _load_provider(settings: Settings) -> LLMProvider | None:
    """Load primary LLM provider via the re-exported name from this module.

    Tests monkeypatch ``bangla_gpt_api.main.get_provider`` — because this
    function calls the name from **this module's namespace**, the patch fires.
    """
    try:
        return get_provider(settings)
    except ProviderNotConfigured:
        return None


def _load_fast_provider(settings: Settings) -> LLMProvider | None:
    """Load the optional fast (SIMPLE route) provider."""
    try:
        return get_fast_provider(settings)
    except ProviderNotConfigured:
        return None


def _load_fallback_chain(
    settings: Settings, provider: LLMProvider
) -> tuple[CircuitBreaker | None, LLMProvider | None]:
    """Build circuit breaker + fallback provider chain."""
    if not settings.llm_fallback_provider:
        return None, None

    from bangla_gpt_api.providers import get_fallback_provider

    circuit_breaker = CircuitBreaker(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        reset_timeout_seconds=settings.circuit_breaker_reset_timeout_seconds,
        name=settings.llm_provider,
    )
    try:
        fallback_provider = get_fallback_provider(settings)
    except ProviderNotConfigured:
        fallback_provider = None

    if fallback_provider is None:
        logger.warning(
            "llm_fallback_missing_key",
            extra={"op": "init", "fallback_provider": settings.llm_fallback_provider},
        )
    return circuit_breaker, fallback_provider


# ---------------------------------------------------------------------------
# Application factory (thin orchestrator — ~25 lines)
# ---------------------------------------------------------------------------


def create_app(settings: Settings | None = None) -> object:
    """Create the FastAPI application.

    Thin orchestrator that delegates to modular initializers.
    No domain logic lives here — every concern is in :mod:`bangla_gpt_api.initialize`.
    """
    settings = settings or get_settings()

    # Phase 1: Observability (logging + Sentry)
    configure_observability_with_sentry(settings)

    # Phase 2: Production safety gate (fail-fast)
    enforce_production_safety(settings)

    # Phase 3: Bare FastAPI app + CORS
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title=settings.app_name, version=settings.version)
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
        )

    # Phase 4: Build providers (so tests that monkeypatch main.get_provider work)
    provider = _load_provider(settings)
    fast_provider = _load_fast_provider(settings) if provider is not None else None
    circuit_breaker, fallback_provider = (
        _load_fallback_chain(settings, provider) if provider is not None else (None, None)
    )

    cache = caching.build_cache(settings)
    app.state.cache = cache

    # Phase 5: Build remaining dependencies (DB, admin) + AppContext
    # Pass re-exported names so monkeypatches on main.HybridIndex /
    # main.make_engine fire during testing.
    ctx, _p, _fp, engine, session_factory = build_dependencies(
        settings,
        cache,
        provider,
        fast_provider,
        circuit_breaker,
        fallback_provider,
        hybrid_index_cls=HybridIndex,
        make_engine_fn=make_engine,
    )
    app.state.ctx = ctx

    # Phase 6: Register middleware (rate limit, body size, security, prometheus)
    from bangla_gpt_api.ratelimit import build_limiter as _bl

    limiter = _bl(settings)
    build_middleware_stack(app, settings, limiter)

    # Phase 7: Register routers
    register_routers(app)

    # Phase 8: Build lifespan (explicit params — no closure capture)
    app.router.lifespan_context = initialize.build_lifespan(
        settings=settings,
        provider=provider,
        fast_provider=fast_provider,
        session_factory=session_factory,
        engine=engine,
    )

    return app


# ---------------------------------------------------------------------------
# Default app instance (for gunicorn --worker-class uvicorn_worker.UvicornWorker)
# ---------------------------------------------------------------------------

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "bangla_gpt_api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="debug",
    )
