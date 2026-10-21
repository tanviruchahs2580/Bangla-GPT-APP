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
        # F-076: two more account-creating / secret-consuming surfaces with no
        # limit at all. Registration is unauthenticated and each call runs
        # Argon2id plus a verification email, so an unbounded caller is an
        # unbounded mail pump and CPU burner. The authenticated MFA legs are
        # scoped per user rather than per IP, because a school NAT puts a
        # whole class behind one address; the genuine brute-force surface is
        # /auth/mfa/challenge above, which keeps the tighter bound.
        "/auth/register": (10, "ip"),
        "/auth/mfa": (20, "user"),
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

    **Starlette builds the stack in reverse**: ``add_middleware`` *prepends*,
    so the LAST middleware registered here is the OUTERMOST one, i.e. the
    first to see a request and the last to see a response.

    Desired request order, outermost first::

        1. Prometheus   - observe every request and every failure
        2. SecurityHeaders - headers on every response, including error responses
        3. RequestId    - a request id exists for every log line and 500 body
        4. CORS         - answer preflight before it costs a rate-limit token
        5. RateLimit    - throttle BEFORE the body is read from the socket
        6. BodySize     - last gate before the body reaches a handler

    That means registration order is the exact reverse of the list above. The
    previous version registered CORS, RateLimit, BodySize, RequestId,
    SecurityHeaders, Prometheus and documented them as if registration order
    were execution order. The real order was Prometheus → SecurityHeaders →
    RequestId → BodySize → RateLimit, so the body-size middleware streamed the
    whole request into memory *before* the rate limiter ever counted it.
    """
    # Explicit ``RATE_LIMIT_RULES`` entries apply to every route except the
    # four with dedicated per-field knobs (see _effective_rules). Previously
    # the config-driven dict was computed and then discarded.
    rl_rules = rules if rules is not None else _effective_rules(settings)

    # Innermost first: reverse of the desired execution order.
    #
    # Body size (rejects oversized payloads before a handler is reached)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)

    # Rate limiting. Registered after BodySize so it wraps it: a throttled
    # request must never have had its body read.
    app.add_middleware(
        RateLimitMiddleware,
        rules=rl_rules,
        limiter=limiter,
        settings=settings,
    )

    # CORS (outside the throttle so preflight responses stay clean)
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

    # Request ID tracing
    app.add_middleware(RequestIdMiddleware)

    # Security headers on every response
    app.add_middleware(SecurityHeadersMiddleware)

    # Prometheus metrics (observe every request) — outermost
    app.add_middleware(PrometheusMetricsMiddleware)

    # I-03 (AUD-HI-04): OpenTelemetry server spans. The instrumentor replaces
    # ``app.build_middleware_stack``, so the span covers every middleware above
    # and every error handler; registered last because nothing may wrap it.
    # No-op unless TRACING_ENABLED is set (tracing.instrument_app).
    from bangla_gpt_api import tracing

    tracing.instrument_app(app)
