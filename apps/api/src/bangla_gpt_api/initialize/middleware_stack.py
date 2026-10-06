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
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
        )

    # Build rate-limit rules from individual settings so test overrides take effect.
    # This mirrors the logic in ``ratelimit.build_limiter`` so the middleware
    # and limiter see identical limits.
    rl_rules = (
        rules
        if rules is not None
        else {
            "/auth/login": (settings.rate_limit_login_per_minute, "ip"),
            "/tutor/ask": (settings.rate_limit_tutor_per_minute, "user"),
            "/tutor/chat": (settings.rate_limit_tutor_per_minute, "user"),
            "/tutor": (settings.rate_limit_tutor_ip_per_minute, "ip"),
            "/auth/forgot": (10, "ip"),
            "/auth/reset": (10, "ip"),
            "/events": (60, "ip"),
        }
    )

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
