"""HTTP middlewares — single canonical home (SEC-003).

Moved verbatim from main.py; the drifted duplicate at ``core/middleware.py``
(static CSP, divergent Prometheus labels) is deleted. Behavior unchanged.
"""

import asyncio
import ipaddress
import logging
import re
import secrets
import uuid
from time import perf_counter
from typing import ClassVar

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bangla_gpt_api.auth.security import decode_token
from bangla_gpt_api.config import Settings
from bangla_gpt_api.logging_config import request_id_var
from bangla_gpt_api.metrics import (
    REQUEST_LATENCY_SECONDS,
    REQUESTS_TOTAL,
    UNHANDLED_EXCEPTIONS_TOTAL,
)
from bangla_gpt_api.ratelimit import RateLimitBackendError, RateLimiter

#: Label used when no route matched the request. A fixed sentinel rather than
#: the raw URL keeps the Prometheus label set bounded (see
#: ``PrometheusMetricsMiddleware._route_path``).
UNMATCHED_ROUTE_LABEL = "<unmatched>"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # sanitize client-supplied X-Request-ID (≤64, [A-Za-z0-9._-]) else generate
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


def _forwarded_ip(request: Request) -> str | None:
    """The LAST valid IP in ``X-Forwarded-For``, or None when there is none.

    With a correctly configured trusted proxy the header holds whatever the
    client sent, followed by the peer address the proxy itself appended
    (nginx's ``$proxy_add_x_forwarded_for`` / Caddy's default). Only that last
    entry is trustworthy: every entry to its left came off the wire from the
    client and can be spoofed. Reading the FIRST entry -- the previous
    behaviour -- let any caller rotate a fake XFF value and bypass every
    IP-scoped limit.

    Entries are parsed with :mod:`ipaddress`, so header junk (a spoofed
    hostname, a port suffix, an empty element) is skipped rather than
    accepted as an identity. When no element parses, the caller falls back to
    the transport peer (``request.client.host``).
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    for candidate in reversed(forwarded.split(",")):
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return candidate
    return None


def _client_ip(request: Request, *, trust_proxy: bool) -> str:
    """Client identity for IP-scoped rate limits.

    Only meaningful behind a reverse proxy that APPENDS the real peer to
    ``X-Forwarded-For`` (not one that overwrites, and it must be the only
    trusted hop): the appended entry is the last one, and that is what is
    read here (S-001). Without a trusted proxy the transport peer is used.
    """
    if trust_proxy:
        forwarded = _forwarded_ip(request)
        if forwarded:
            return forwarded
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
        # evaluate ALL matching rules (not first-match break) so
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
                # The Redis limiter is a sync client (socket_timeout=1s); a
                # degraded backend must cost a worker-thread stall, not an
                # event-loop stall of every concurrent stream on this worker.
                allowed = await asyncio.to_thread(
                    self.limiter.check, f"{path_prefix}|{key_source}", limit
                )
            except RateLimitBackendError:
                return JSONResponse({"detail": "Rate limiter unavailable"}, status_code=503)
            if not allowed:
                # Retry-After so a throttled client waits instead of guessing
                # (the auth lockout path already sends it; API-05).
                wait_seconds = self.limiter.retry_after(f"{path_prefix}|{key_source}")
                return JSONResponse(
                    {"detail": {"code": "rate_limited", "message": "Rate limit exceeded"}},
                    status_code=429,
                    headers={"Retry-After": str(wait_seconds)},
                )
        return await call_next(request)


class _BodyTooLarge(Exception):
    """Internal signal: the running byte count passed ``max_bytes``."""


class BodySizeLimitMiddleware:
    """Reject oversized request bodies **without buffering them**.

    This is a pure-ASGI middleware, deliberately not a ``BaseHTTPMiddleware``.
    Two reasons, both learned the hard way:

    * **The old implementation was not a limit.** It called
      ``await request.body()`` as the chunked-transfer safety net, and that
      buffers the *entire* body into memory before the length is checked.
      starlette 1.7.0 applies no cap of its own, so an unauthenticated caller
      sending a chunked request with no ``Content-Length`` could make the
      process allocate an arbitrary amount of memory. Because this middleware
      was also *inside* the rate limiter (see
      ``initialize.middleware_stack``), the allocation happened before the
      request was ever counted.
    * **A ``BaseHTTPMiddleware`` rewrite deadlocks.** Draining ``receive``
      directly from a ``BaseHTTPMiddleware.dispatch`` bypasses starlette's
      ``_CachedRequest``, whose ``wrapped_receive`` then waits on an already
      exhausted channel for a disconnect that never arrives. Every request
      hangs. Consuming ``request.stream()`` instead is worse: completing the
      stream makes ``_CachedRequest`` hand downstream an *empty* body.

    Wrapping ``receive`` and counting as the application pulls is the only
    shape that is both bounded and correct: the application still sees the
    real, streaming body, and this middleware never holds more than the single
    chunk in flight.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    @staticmethod
    def _response(status: int, detail: str) -> Response:
        return JSONResponse({"detail": detail}, status_code=status)

    @staticmethod
    def _declared_length(scope: Scope) -> int | None:
        """The ``Content-Length`` value, or None when it is absent/unusable."""
        for key, value in scope.get("headers", ()):
            if key == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Fast path: a declared length over the limit is rejected before a
        # single body byte is read.
        declared = self._declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            await self._response(413, "Request body too large")(scope, receive, send)
            return

        total = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b"") or b"")
                if total > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                # The application already committed to a response; the only
                # honest thing left is to let the error surface.
                raise
            await self._response(413, "Request body too large")(scope, receive, send)
        except (OSError, MemoryError):
            # The stream failed mid-read. Forwarding would leave the endpoint
            # waiting on a body that will never arrive — fail clean instead.
            if response_started:
                raise
            await self._response(400, "Unable to read request body")(scope, receive, send)


#: HSTS lifetime. Must match the edge's value (deploy/caddy/Caddyfile) so a
#: response that reaches a browser through either hop pins the same policy.
HSTS_MAX_AGE_SECONDS = 31_536_000


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers on every API response."""

    # Applied both to responses that flow back through the middleware stack and
    # to the 500 built by ``unhandled_exception_response`` below. A 500 raised
    # inside ``call_next`` propagates as an exception, so it never passes back
    # through this ``dispatch``; without the shared helper the failure
    # response — the one an operator most needs to diagnose — would be the only
    # response in the application with no CSP, no nosniff and no frame
    # protection.
    BASELINE_HEADERS: ClassVar[dict[str, str]] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
    }

    #: Dev surfaces that bootstrap with inline + CDN scripts and are therefore
    #: deliberately exempt from the nonce policy.
    CSP_EXEMPT_PATHS: ClassVar[tuple[str, ...]] = ("/docs", "/redoc", "/openapi.json")

    @classmethod
    def apply_csp(cls, response: Response, path: str) -> Response:
        # CSP with a per-response nonce. The API itself only returns JSON (the
        # nonce is belt-and-braces for any future HTML response). The SPA ships
        # no inline script at all (apps/web/public/theme-boot.js is a static
        # file), so Caddy serves it a plain script-src 'self' policy -- the
        # stock caddy:2-alpine image cannot mint nonces (verified against
        # v2.11.4).
        if path in cls.CSP_EXEMPT_PATHS:
            return response
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

    @classmethod
    def apply_baseline(cls, response: Response, path: str = "") -> Response:
        """Every hardening header, for responses that bypass the stack.

        Used both by ``dispatch`` and by ``unhandled_exception_response``: an
        exception raised inside ``call_next`` never returns through this
        middleware, so without this the failure response — the one an operator
        most needs to diagnose — would be the only response in the application
        with no CSP, no nosniff and no frame protection.
        """
        for header, value in cls.BASELINE_HEADERS.items():
            response.headers.setdefault(header, value)
        cls.apply_csp(response, path)
        return response

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        self.apply_baseline(response, request.url.path)
        settings = getattr(request.app.state, "settings", None)
        if settings is not None and settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains",
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
        """Route template for the metric labels, or a fixed sentinel.

        The route is only resolved once routing has matched, so a request that
        matches nothing (404, or a path that never existed) falls back here.
        Falling back to ``request.url.path`` made the label attacker-controlled:
        100 distinct 404 URLs produced 100 new time series in an
        unauthenticated endpoint, which is a memory-growth vector against the
        scrape target and the log store, for free, from outside.
        """
        route = request.scope.get("route")
        template = getattr(route, "path", None)
        if template:
            return str(template)
        return UNMATCHED_ROUTE_LABEL


def unhandled_exception_response(request: Request, exc: Exception) -> JSONResponse:
    """Build the 500 body for an exception no handler claimed.

    Two things this fixes, both observed rather than theorised:

    * FastAPI's default 500 is produced by ``ServerErrorMiddleware``, the
      OUTERMOST middleware. An exception raised inside ``call_next`` therefore
      never returns through ``SecurityHeadersMiddleware`` or
      ``RequestIdMiddleware``, so the 500 went out with no ``X-Request-ID``,
      no CSP, no ``nosniff`` and no frame protection. ``docs/API.md`` claimed
      every response carries ``X-Request-ID``; this was false precisely on the
      responses an operator most needs to trace.
    * The body is a fixed, coded envelope. The exception type, message and
      traceback stay in the server-side log, correlated by request id. Nothing
      from ``exc`` is interpolated into the response, so a
      ``ValueError`` carrying a connection string or a row of PII cannot leak
      to a client.

    Registered by :func:`bangla_gpt_api.main.create_app` as a handler for
    ``Exception``.
    """
    request_id = getattr(request.state, "request_id", None) or request_id_var.get()
    logger = logging.getLogger("bangla_gpt_api.unhandled")
    logger.exception(
        "unhandled_exception",
        extra={
            "op": "request",
            "method": request.method,
            "path": request.url.path,
            "exc_type": type(exc).__name__,
        },
    )
    body: dict[str, object] = {
        "detail": {
            "code": "internal_error",
            "message": "An unexpected error occurred",
        }
    }
    if request_id:
        body["request_id"] = request_id
    response = JSONResponse(body, status_code=500)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    SecurityHeadersMiddleware.apply_baseline(response, request.url.path)
    return response
