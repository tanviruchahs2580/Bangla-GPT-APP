"""HTTP middlewares — single canonical home (SEC-003).

Moved verbatim from main.py; the drifted duplicate at ``core/middleware.py``
(static CSP, divergent Prometheus labels) is deleted. Behavior unchanged.
"""

import re
import secrets
import uuid
from time import perf_counter

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from bangla_gpt_api.auth.security import decode_token
from bangla_gpt_api.config import Settings
from bangla_gpt_api.logging_config import request_id_var
from bangla_gpt_api.metrics import (
    REQUEST_LATENCY_SECONDS,
    REQUESTS_TOTAL,
    UNHANDLED_EXCEPTIONS_TOTAL,
)
from bangla_gpt_api.ratelimit import RateLimitBackendError, RateLimiter


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # F-SEC-05: sanitize client-supplied X-Request-ID (≤64, [A-Za-z0-9._-]) else generate
        raw = request.headers.get("X-Request-ID")
        if raw and len(raw) <= 64 and re.fullmatch(r"[A-Za-z0-9._-]+", raw):
            request_id = raw
        else:
            request_id = uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


def _client_ip(request: Request, *, trust_proxy: bool) -> str:
    """Client identity for IP-scoped rate limits.

    Behind a trusted reverse proxy the real client IP arrives in
    X-Forwarded-For; enable only when the proxy overwrites (not appends)
    that header, otherwise clients can spoof it.
    """
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip() if forwarded else ""
        if first:
            return first
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiting with IP and per-user scopes.

    Authenticated routes use a per-user key when a valid Bearer token is
    present (C15: one school NAT must not lock out a whole classroom), while
    an IP ceiling still guards against token-farm abuse.
    """

    def __init__(
        self, app, rules: dict[str, tuple[int, str]], limiter: "RateLimiter", settings: Settings
    ) -> None:
        super().__init__(app)
        self.rules = rules
        self.limiter = limiter
        self._settings = settings

    @staticmethod
    def _user_key(request: Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        try:
            payload = decode_token(auth[7:], settings=request.app.state.settings)
            return f"u:{payload['sub']}"
        except Exception:
            return None

    async def dispatch(self, request: Request, call_next):
        client_ip = _client_ip(request, trust_proxy=self._settings.trust_proxy_headers)
        # F-SEC-02: evaluate ALL matching rules (not first-match break) so
        # per-user and IP ceiling both apply; a single request counts once per limiter
        for path_prefix, (limit, scope) in self.rules.items():
            if not request.url.path.startswith(path_prefix) or limit <= 0:
                continue
            if scope == "user":
                # Per-user budget so a shared school NAT cannot lock out a
                # classroom; unauthenticated callers fall back to their IP.
                user_key = self._user_key(request)
                key_source = user_key or f"ip:{client_ip}"
            else:
                key_source = f"ip:{client_ip}"
            # Strict prefix matching: "/tutor" matches "/tutor/" and "/tutor/ask"
            # but NOT "/tutor-admin" (avoids false positives).
            path = request.url.path
            if not (path == path_prefix or path.startswith(path_prefix + "/")):
                continue
            try:
                allowed = self.limiter.check(f"{path_prefix}|{key_source}", limit)
            except RateLimitBackendError:
                return JSONResponse({"detail": "Rate limiter unavailable"}, status_code=503)
            if not allowed:
                return JSONResponse(
                    {"detail": {"code": "rate_limited", "message": "Rate limit exceeded"}},
                    status_code=429,
                )
        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        # Fast path: Content-Length header (reject oversized requests immediately)
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        # F-SEC-04: byte-counting safety net for chunked / absent Content-Length.
        # request.body() buffers the full body; we already rejected oversized via
        # Content-Length above, so the fallback only catches chunked transfers.
        try:
            body = await request.body()
            if len(body) > self.max_bytes:
                return JSONResponse({"detail": "Request body too large"}, status_code=413)

            # Replay body for downstream (BaseHTTPMiddleware consumes receive;
            # we must reconstruct).
            async def _replay_receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(request.scope, receive=_replay_receive)
        except Exception:
            pass
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers on every API response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        # S5.6: CSP with a per-response nonce. The API itself only returns
        # JSON (the nonce is belt-and-braces for any future HTML response).
        # The SPA ships no inline script at all (apps/web/public/theme-boot.js
        # is a static file), so Caddy serves it a plain script-src 'self'
        # policy -- the stock caddy:2-alpine image cannot mint nonces (verified
        # against v2.11.4). /docs and /redoc bootstrap with inline + CDN
        # scripts and are deliberately exempt (dev surfaces).
        if request.url.path not in ("/docs", "/redoc", "/openapi.json"):
            nonce = secrets.token_urlsafe(16)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; font-src 'self' data:; "
                "connect-src 'self'; object-src 'none'; base-uri 'self'; "
                "form-action 'self'; frame-ancestors 'none'"
            )
        return response


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Count every request and observe latency, labeled by route template."""

    async def dispatch(self, request: Request, call_next):
        start = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            UNHANDLED_EXCEPTIONS_TOTAL.labels(
                method=request.method, path=self._route_path(request)
            ).inc()
            raise
        finally:
            elapsed = perf_counter() - start
            path = self._route_path(request)
            REQUESTS_TOTAL.labels(method=request.method, path=path, status=str(status_code)).inc()
            REQUEST_LATENCY_SECONDS.labels(path=path).observe(elapsed)

    @staticmethod
    def _route_path(request: Request) -> str:
        route = request.scope.get("route")
        return getattr(route, "path", request.url.path)
