"""Middleware extracted from main.py (Phase 2.2) — behavior-preserving move.

Contains: RequestId, BodySizeLimit, SecurityHeaders, RateLimit, Prometheus.
BodySizeLimit now enforces byte-counting safety net (F-SEC-04) via request.body().
"""

import re
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


def _client_ip(request: Request, *, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip() if forwarded else ""
        if first:
            return first
    return request.client.host if request.client else "unknown"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
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


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        rules: dict[str, tuple[int, str]],
        limiter: RateLimiter,
        settings: Settings,
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
        for path_prefix, (limit, scope) in self.rules.items():
            if not request.url.path.startswith(path_prefix) or limit <= 0:
                continue
            if scope == "user":
                user_key = self._user_key(request)
                key_source = user_key or f"ip:{client_ip}"
            else:
                key_source = f"ip:{client_ip}"
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
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        try:
            body = await request.body()
            if len(body) > self.max_bytes:
                return JSONResponse({"detail": "Request body too large"}, status_code=413)

            async def _replay_receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(request.scope, receive=_replay_receive)
        except Exception:
            pass
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        return response


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
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
            REQUEST_LATENCY_SECONDS.labels(method=request.method, path=path).observe(elapsed)

    @staticmethod
    def _route_path(request: Request) -> str:
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            return route.path
        return request.url.path
