"""Middleware stack builder.

Extracted from the monolithic ``main.py``. Each middleware is configured once
with its own settings and attached to the ``FastAPI`` app in deterministic order.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bangla_gpt_api.config import Settings
from bangla_gpt_api.middleware import (
    BodySizeLimitMiddleware,
    PrometheusMetricsMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from bangla_gpt_api.ratelimit import RateLimiter


def _derive_default_rules(settings: Settings) -> dict[str, tuple[int, str]]:
    """Per-route rate limits derived from individual settings so test
    overrides of the per-field knobs take effect."""
    return {
        "/auth/login": (settings.rate_limit_login_per_minute, "ip"),
        # TOTP second factor: 6-digit space with a ±1 step window —
        # without this rule the challenge endpoint is brute-forceable.
        "/auth/mfa/challenge": (5, "ip"),
        "/tutor/ask": (settings.rate_limit_tutor_per_minute, "user"),
        # The chat LLM routes are /tutor/conversations/{id}/messages[/stream];
        # a "/tutor/chat" key matches no real path.
        "/tutor/conversations": (settings.rate_limit_tutor_per_minute, "user"),
        "/tutor": (settings.rate_limit_tutor_ip_per_minute, "ip"),
        "/auth/forgot": (10, "ip"),
        "/auth/reset": (10, "ip"),
        "/auth/resend-verification": (10, "ip"),
        "/auth/verify-email": (10, "ip"),
        "/events": (60, "ip"),
    }


#: Routes whose limit is configurable through the dedicated per-field knobs
#: (RATE_LIMIT_LOGIN_PER_MINUTE etc.). On these routes the knobs win over
#: RATE_LIMIT_RULES; everywhere else RATE_LIMIT_RULES entries apply as given.
_PER_FIELD_ROUTES = frozenset({"/auth/login", "/tutor/ask", "/tutor/conversations", "/tutor"})


def _effective_rules(settings: Settings) -> dict[str, tuple[int, str]]:
    """Merge per-field knob rules with the config-driven ``RATE_LIMIT_RULES``.

    Precedence: per-field knobs on their four routes, ``RATE_LIMIT_RULES``
    for every other route, derived defaults fill the rest. Previously the
    config-driven dict was computed and then discarded, so operators
    setting ``RATE_LIMIT_RULES`` silently changed nothing.
    """
    rules = dict(settings.rate_limit_rules)
    for route, rule in _derive_default_rules(settings).items():
        if route in _PER_FIELD_ROUTES or route not in rules:
            rules[route] = rule
    return rules


def build_middleware_stack(
    app: FastAPI,
    settings: Settings,
    limiter: RateLimiter,
    rules: dict[str, tuple[int, str]] | None = None,
) -> None:
    """Register all middleware on ``app`` in deterministic order.

    Order matters:
    1. CORS — must run before request processing so preflight responses are clean
    2. Rate limiting — gate traffic before body parsing
    3. Body size — reject oversized payloads early
    4. Request ID — trace every request
    5. Security headers — every outgoing response
    6. Prometheus — observe every request (including 4xx)
    """
    # CORS (before everything else so preflight responses are clean)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            # PATCH is used by admin/parent/tutor/workspace endpoints — the
            # SPA breaks on cross-origin preflights without it.
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
        )

    # Explicit ``RATE_LIMIT_RULES`` entries apply to every route except the
    # four with dedicated per-field knobs (see _effective_rules). Previously
    # the config-driven dict was computed and then discarded.
    rl_rules = rules if rules is not None else _effective_rules(settings)

    # Rate limiting (before body parsing so we reject before expensive work)
    app.add_middleware(
        RateLimitMiddleware,
        rules=rl_rules,
        limiter=limiter,
        settings=settings,
    )

    # Body size limit (before downstream middleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)

    # Request ID tracing
    app.add_middleware(RequestIdMiddleware)

    # Security headers on every response
    app.add_middleware(SecurityHeadersMiddleware)

    # Prometheus metrics (observe every request)
    app.add_middleware(PrometheusMetricsMiddleware)
