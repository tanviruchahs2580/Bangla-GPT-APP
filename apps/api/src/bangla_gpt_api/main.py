"""Bangla GPT API — application bootstrap (slim entrypoint).

All domain routes live in:mod:`bangla_gpt_api.routers` (split);
this module keeps only boot concerns: settings, observability, dependency
construction, middleware, lifespan and the gunicorn ``app``.

The monolithic ``main.py`` (previously ~7000 lines) has been refactored into:

- ``initialize/observability``: logging + Sentry bootstrap
- ``initialize/middleware_stack``: all middleware registration
- ``initialize/dependencies``: index/DB/admin construction (providers passed in)
- ``initialize/lifespan``: lifespan context with explicit params
- ``initialize/schedulers``: background scheduler loops with health monitoring

All these modules are imported from:mod:`bangla_gpt_api.initialize`.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet

from bangla_gpt_api import caching, initialize
from bangla_gpt_api.config import (
    DEFAULT_JWT_SECRET,
    NON_PRODUCTION_ENVS,
    PRODUCTION_ENVS,
    Settings,
    get_settings,
)

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
from bangla_gpt_api.logging_config import set_secret_logging_allowed
from bangla_gpt_api.middleware import unhandled_exception_response
from bangla_gpt_api.providers import (
    ProviderNotConfigured,  # noqa: F401 (re-exported for tests)
    get_fast_provider,  # noqa: F401 (re-exported for tests)
    get_provider,  # noqa: F401 (re-exported for tests)
)
from bangla_gpt_api.providers.base import (
    WORKER_TIMEOUT_SECONDS,
    fit_timeout,
    worst_case_seconds,
)
from bangla_gpt_api.ratelimit import build_limiter  # noqa: F401 (re-exported for tests)
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex  # noqa: F401 (re-exported for tests)
from bangla_gpt_api.routers import register_routers
from bangla_gpt_api.routers._error_contract import CodedDetail, MessageDetail
from bangla_gpt_api.routers.deps import CONSENT_VERSION
from bangla_gpt_api.services.circuit_breaker import CircuitBreaker  # noqa: F401
from bangla_gpt_api.services.tutor import TutorService  # noqa: F401 (re-exported for tests)

__all__ = ["CONSENT_VERSION", "app", "create_app", "enforce_production_safety"]
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Production safety validators (separate from create_app for SRP)
# ---------------------------------------------------------------------------


def enforce_production_safety(settings: Settings) -> None:
    """Refuse to boot in production with insecure configuration.

    Each check is a standalone validator function (SRP). When any check
    fails, the combined error is raised as a single RuntimeError.
    """
    if not settings.is_production:
        return

    if settings.rate_limit_backend.strip().lower() == "memory":
        # The multi-worker case is refused by _validate_rate_limit_redis, so
        # this is the single-worker production deployment: logs must name
        # what it gives up, because the README's "revocation fails closed"
        # claim is a Redis guarantee. A memory deny-list dies with the
        # process, and every access token minted before the restart becomes
        # valid again until its own expiry. Audit SEC-02.
        logger.warning(
            "RATE_LIMIT_BACKEND=memory in production: token revocation and "
            "single-use MFA burns are per-process. A restart re-accepts "
            "tokens revoked before it. Use Redis for the fail-closed store."
        )

    problems: list[str] = []

    # ENV-gate guidance (tests/test_env_gate.py): the settings landed here
    # because ENV is not one of the recognized development names -- often a
    # TYPO. Name the offending value and the legit names, so an operator a
    # minute from a launch sees the fix instead of a generic refusal.
    if settings.env.strip().lower() not in PRODUCTION_ENVS:
        problems.append(
            f"ENV={settings.env!r} is not a recognized production name "
            f"({', '.join(sorted(PRODUCTION_ENVS))}); it is being guarded as "
            "production because anything unrecognized is treated as one. "
            f"Development lanes that skip the guard: "
            f"{', '.join(sorted(NON_PRODUCTION_ENVS))}."
        )

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
        _validate_corpus,
        _validate_ai_budget,
        _validate_llm_budget,
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
    """SMTP must be configured in production, else email verification is bypassed."""
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
    """JWT_SECRET must be overridden in production and must have entropy.

    The old check was length-only. ``JWT_SECRET='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'``
    is 32 characters, satisfied every constraint in the previous validator,
    and signs every token in the deployment. Length is necessary; it has never
    been sufficient.
    """
    if settings.jwt_secret == DEFAULT_JWT_SECRET or len(settings.jwt_secret) < 32:
        return ["JWT_SECRET must be overridden in production with at least 32 random characters"]
    weak = _weak_secret_reason(settings.jwt_secret)
    if weak:
        return [f"JWT_SECRET is too predictable: {weak}"]
    return []


def _weak_secret_reason(secret: str) -> str | None:
    """Why this secret would fall to a trivial guessing attack, or None."""
    if len(set(secret)) <= 4:
        return (
            f"it uses only {len(set(secret))} distinct characters "
            "(32 of the same character passes a length check)"
        )
    lowered = secret.lower()
    if lowered in _WEAK_SECRETS:
        return "it is a well-known placeholder value"
    # A single repeated unit, e.g. "abcabcabc..." or "123456123456...".
    for unit in (3, 4, 6, 8, 12, 16):
        if len(secret) % unit == 0 and secret[:unit] * (len(secret) // unit) == secret:
            return f"it is a single {unit}-character block repeated"
    # A pure ascending/descending run (checked arithmetically: chr() on a
    # 64-byte urlsafe token walks off the end of the code point range).
    deltas = {ord(secret[i + 1]) - ord(secret[i]) for i in range(len(secret) - 1)}
    if len(deltas) == 1 and deltas.pop() in (1, -1):
        return "it is a sequential character run"
    return None


#: Placeholder secrets that ship in templates, compose files and blog posts.
_WEAK_SECRETS = frozenset(
    {
        "change-me-change-me-change-me",
        "changemechangemechangeme",
        "replace-me-with-a-real-secret",
        "your-secret-key-goes-here!",
        "please-change-this-secret",
    }
)


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
    url = settings.database_url.strip()
    if url in ("sqlite://", "sqlite:///:memory:") or ":memory:" in url:
        return [
            "DATABASE_URL must be a persistent store in production "
            "(e.g. sqlite:////data/app.db or PostgreSQL)"
        ]
    # A file-backed SQLite database is accepted above, but it is not safe
    # behind multiple workers: SQLite serialises writers, so two gunicorn
    # workers contend on the write lock and concurrent writes fail or block.
    # compose defaults ENV=production with sqlite:////data/app.db, so this
    # combination was reachable by simply running the documented stack.
    if url.startswith("sqlite") and _worker_count(settings) > 1:
        return [
            "DATABASE_URL is SQLite while WEB_CONCURRENCY="
            f"{_worker_count(settings)}; SQLite serialises writers and is not safe "
            "with multiple workers. Use PostgreSQL, or run a single worker."
        ]
    return []


def _worker_count(settings: Settings) -> int:
    """Worker count gunicorn would start (mirrors the container CMD).

    Fails safe: anything that is not a positive integer -- unset, empty,
    unparseable, zero or negative -- is reported as the container default of 2.
    Clamping to 1 instead would silently switch the SQLite and rate-limit
    guards OFF, which is the opposite of what an invalid value should do.
    """
    raw = os.environ.get("WEB_CONCURRENCY", "").strip()
    try:
        n = int(raw)
    except ValueError:
        return 2
    return n if n >= 1 else 2


def _validate_pii(settings: Settings) -> list[str]:
    """PII_ENC_KEY must be a real Fernet key in production, and the
    plaintext fallback must be off.

    The old check was ``if not settings.pii_enc_key``. A value that is present
    but malformed -- "not-a-fernet-key" -- passed the boot gate and then raised
    ``ValueError`` on the first guardian phone that needed encrypting, i.e.
    the guard failed at the worst possible moment rather than at startup.
    The plaintext fallback (PII_ALLOW_PLAINTEXT) is a dev/test convenience;
    booting a production pilot with it enabled must not be possible.
    """
    if settings.pii_allow_plaintext:
        return [
            "PII_ALLOW_PLAINTEXT must be false in production: guardian phones "
            "would be stored unencrypted. Set PII_ENC_KEY (a valid Fernet key) instead."
        ]
    if not settings.pii_enc_key:
        return ["PII_ENC_KEY must be set in production (guardian phone encryption)"]
    try:
        Fernet(settings.pii_enc_key.encode())
    except (ValueError, TypeError) as exc:
        return [
            "PII_ENC_KEY is not a valid Fernet key "
            f"({type(exc).__name__}); generate one with "
            '`python -c "from cryptography.fernet import Fernet;'
            'print(Fernet.generate_key().decode())"`'
        ]
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
    """Rate limiting must work across workers, so memory is not enough."""
    backend = settings.rate_limit_backend.strip().lower()
    if backend == "redis" and not settings.redis_url:
        return ["RATE_LIMIT_BACKEND=redis requires REDIS_URL"]
    # With multiple workers each process keeps its own counters, so the
    # configured limit is effectively multiplied by the worker count: the
    # default 10/minute login limit becomes 20/minute behind two workers.
    if backend == "memory" and _worker_count(settings) > 1:
        return [
            "RATE_LIMIT_BACKEND=memory is per-process and therefore per-worker; "
            f"with WEB_CONCURRENCY={_worker_count(settings)} the effective limit is "
            "multiplied by the worker count. Use RATE_LIMIT_BACKEND=redis with "
            "REDIS_URL in production."
        ]
    return []


def _validate_llm_provider(settings: Settings) -> list[str]:
    """The mock provider must never serve production traffic."""
    provider = settings.llm_provider.strip().lower()
    if provider == "gemini" and not settings.gemini_api_key:
        return ["LLM_PROVIDER=gemini requires GEMINI_API_KEY in production"]
    # compose defaults ENV=production and LLM_PROVIDER=mock, so the documented
    # stack booted in production mode serving fabricated tutor answers with no
    # error. LLM-01 requires the mock provider to be impossible in production.
    if provider == "mock" and not _mock_allowed(settings):
        return [
            "LLM_PROVIDER=mock must not be used in production: it serves "
            "fabricated answers with no error. Set LLM_PROVIDER=gemini with "
            "GEMINI_API_KEY, or set ALLOW_MOCK_LLM_IN_PRODUCTION=true for a "
            "deliberate offline demo."
        ]
    return []


def _mock_allowed(settings: Settings) -> bool:
    return os.environ.get("ALLOW_MOCK_LLM_IN_PRODUCTION", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _validate_corpus(settings: Settings) -> list[str]:
    """A billable production tutor must not answer from the bundled sample (F-016).

    With NCTB_CORPUS_DIR empty -- the documented compose default -- the loader
    falls back to the 78-chunk synthetic sample corpus and the tutor cites it
    as evidence to children. The fallback used to be reported only by a log
    line and a metric, so a Gemini-configured deployment could serve the
    sample to real students with nothing in /ready showing it. The mock
    provider is exempt: it is itself refused in production unless the offline
    demo opt-in is set, serves no real answer, and the sample is coherent with
    a deliberate demo.
    """
    if settings.allow_bundled_sample_corpus_in_production:
        return []
    if not settings.has_billable_llm_provider:
        return []
    if not (settings.nctb_corpus_dir or "").strip():
        return [
            "NCTB_CORPUS_DIR is empty and the LLM provider is billable: the "
            "tutor would answer children from the bundled synthetic sample "
            "corpus and cite it as evidence. Point NCTB_CORPUS_DIR at the "
            "built corpus, or set "
            "ALLOW_BUNDLED_SAMPLE_CORPUS_IN_PRODUCTION=true for a deliberate "
            "offline demo."
        ]
    return []


def _validate_ai_budget(settings: Settings) -> list[str]:
    """A billable production deployment must ship a per-user spend cap (F-034).

    ``ai_monthly_budget_usd_per_user`` defaults to 0 = unlimited and the
    documented production template never mentioned the key, so an operator
    following the template ran with no ceiling at all: the reserve-before-call
    ledger (services/costs.py) works, but the gate was switched off by
    configuration and one looping or abusive account was bounded only by 30
    requests/minute. Refusing boot makes the cap an explicit deployment
    decision; the mock provider is exempt for the same reason as in
    ``_validate_corpus`` (it bills exactly 0).
    """
    if not settings.has_billable_llm_provider:
        return []
    if float(settings.ai_monthly_budget_usd_per_user or 0.0) <= 0:
        return [
            "AI_MONTHLY_BUDGET_USD_PER_USER must be a positive monthly cap in "
            "production when a billable LLM provider is configured (0 means "
            "unlimited). A conservative starting value is 5 (USD per user per "
            "month); raise it deliberately once real usage is measured."
        ]
    return []


def _validate_llm_budget(settings: Settings) -> list[str]:
    """The retry chain must finish before the worker is killed.

    Providers clamp their per-attempt timeout to fit
    ``LLM_TOTAL_BUDGET_SECONDS`` (see ``providers.base.fit_timeout``), so this
    is an assertion rather than the control: it fires if the clamp is ever
    bypassed or the budget is raised past the worker timeout, which would turn
    a slow upstream into a SIGKILL that drops every concurrent request on the
    worker.
    """
    worst = worst_case_seconds(
        fit_timeout(settings.llm_timeout_seconds, settings.llm_max_retries),
        settings.llm_max_retries,
    )
    if worst >= WORKER_TIMEOUT_SECONDS:
        return [
            "LLM timeout/retry budget "
            f"({settings.llm_timeout_seconds}s x {settings.llm_max_retries} retries"
            f" -> {worst:.1f}s) can exceed the gunicorn worker timeout"
            f" ({WORKER_TIMEOUT_SECONDS:.0f}s). Lower LLM_TIMEOUT_SECONDS or "
            "LLM_MAX_RETRIES, or raise --timeout in the container CMD."
        ]
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


# Operations reachable without a session. Listed here, once, so the OpenAPI
# document records a deliberate decision rather than leaving the reader to
# guess. Without it the spec simply omits `security`, which makes an automated
# authorization matrix unable to tell "deliberately public" apart from
# "authentication forgotten" -- which is how a real bypass hides.
#
# Keep in step with tests/test_openapi_auth_matrix.py, which fails if an
# operation here stops existing or if a new operation appears unlisted.
PUBLIC_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # Account entry points: these are public by definition.
        ("post", "/auth/login"),
        ("post", "/auth/register"),
        ("post", "/auth/forgot"),
        ("post", "/auth/reset"),
        ("post", "/auth/verify-email"),
        ("post", "/auth/join-school"),
        ("post", "/auth/mfa/challenge"),
        # Optional auth: the route reads a bearer token when one is supplied
        # and works without it, so FastAPI emits a security requirement that
        # anonymous callers do not actually satisfy. Declared public here so the
        # contract matches the behaviour; the handler still uses the token when
        # present. Abuse of this endpoint is bounded by the per-IP rate limit.
        ("post", "/auth/resend-verification"),
        # Operational probes. /status is a deliberate public status page and
        # returns booleans only (see routers/system.py).
        ("get", "/health"),
        ("get", "/live"),
        ("get", "/ready"),
        ("get", "/status"),
    }
)


def _mark_public_operations(app: object) -> None:
    """Stamp `security: []` on the known-public operations.

    FastAPI omits `security` entirely when a route has no security dependency
    and the document has no global `security`, so a deliberate decision is
    invisible in the contract.
    """
    original = app.openapi  # type: ignore[attr-defined]

    def openapi() -> dict[str, Any]:
        spec: dict[str, Any] = original()
        for path, item in spec.get("paths", {}).items():
            for method, op in item.items():
                if (
                    method.lower() in _HTTP_METHODS
                    and (
                        method.lower(),
                        _normalise_path(path),
                    )
                    in PUBLIC_OPERATIONS
                ):
                    op["security"] = []
        return spec

    # Replacing the attribute on the FastAPI instance is the documented way to
    # customise the schema; mypy types `app` as a bare object here.
    app.openapi = openapi  # type: ignore[attr-defined]


_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


def _normalise_path(path: str) -> str:
    """Collapse trailing slashes so /status/ and /status compare equal."""
    return path.rstrip("/") or path


def create_app(settings: Settings | None = None) -> object:
    """Create the FastAPI application.

    Thin orchestrator that delegates to modular initializers.
    No domain logic lives here — every concern is in:mod:`bangla_gpt_api.initialize`.
    """
    settings = settings or get_settings()

    # Phase 1: Observability (logging + Sentry)
    configure_observability_with_sentry(settings)

    # The reset flow can print a single-use token to the console when SMTP is
    # absent, which is a development affordance and never a production one.
    # Decided here, centrally, so the guarantee does not rest on an `if` at
    # each call site (F-082).
    set_secret_logging_allowed(not settings.is_production)

    # Phase 2: Production safety gate (fail-fast)
    enforce_production_safety(settings)

    # Phase 3: Bare FastAPI app. CORS lives exclusively in
    # initialize.middleware_stack.build_middleware_stack (registered once,
    # together with the rest of the middleware order).
    from fastapi import FastAPI

    # SEC-15: the interactive reference and the machine-readable schema are
    # development surfaces. FastAPI enables all three by default, so without
    # this they are served in production too -- verified: a production-config
    # container answered /openapi.json with 158477 bytes of the full route
    # schema. They are also the only paths exempt from the nonce CSP in
    # middleware.SecurityHeadersMiddleware. Disabled in production, kept in
    # development where they are the whole point.
    serve_docs = not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/docs" if serve_docs else None,
        redoc_url="/redoc" if serve_docs else None,
        openapi_url="/openapi.json" if serve_docs else None,
        # The rate-limit and body-size guards are global middleware, so every
        # operation can answer 429/503. Declaring them on the app documents
        # them once instead of on each route (AUD-0055).
        responses={
            429: {"model": CodedDetail, "description": "Rate limit exceeded"},
            503: {"model": MessageDetail, "description": "Rate limiter backend unavailable"},
        },
    )
    _mark_public_operations(app)
    app.state.settings = settings

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

    # Phase 6: Register middleware (rate limit, body size, security, prometheus).
    # build_limiter is the module-level re-export on purpose: a local import
    # here shadows it, so the monkeypatch seam this module documents for tests
    # (see the import block at the top) silently stopped working -- and a test
    # that believed it was injecting a dead limiter was really exercising the
    # real Redis one.
    limiter = build_limiter(settings)
    build_middleware_stack(app, settings, limiter)

    # Phase 7: Register routers
    register_routers(app)

    # Phase 7b: Last-resort handler for an exception no route claimed. Without
    # it the 500 is produced by ServerErrorMiddleware, the OUTERMOST layer, so
    # it bypasses RequestIdMiddleware and SecurityHeadersMiddleware and ships
    # with no X-Request-ID and no hardening headers (F-083).
    app.add_exception_handler(Exception, unhandled_exception_response)

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
        host="0.0.0.0",  # noqa: S104 - a container listens on all interfaces by design; the proxy is the boundary
        port=8000,
        reload=True,
        log_level="debug",
    )
