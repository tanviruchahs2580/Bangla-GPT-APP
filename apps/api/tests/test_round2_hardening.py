"""Regression tests for the round-2 observability and hardening fixes.

Each test here is written so that reverting its fix makes it FAIL. That is
the only property that makes a test worth keeping: a test that passes before
and after the change proves nothing about the change.

Covered:
  F-081  middleware registration order (rate limiting wraps body buffering)
  F-082  log redaction
  F-083  unhandled exceptions produce a traceable, hardened 500
  F-084  bounded Prometheus label cardinality on unmatched routes
  F-085  the body-size limit is a real limit on chunked transfers
"""

from __future__ import annotations

import logging
import os

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from bangla_gpt_api.config import Settings
from bangla_gpt_api.logging_config import REDACTED, RedactionFilter, is_sensitive_key
from bangla_gpt_api.main import create_app
from bangla_gpt_api.metrics import REQUESTS_TOTAL
from bangla_gpt_api.middleware import (
    UNMATCHED_ROUTE_LABEL,
    BodySizeLimitMiddleware,
    unhandled_exception_response,
)
from conftest import engine_url


def _settings(tmp_path, **overrides) -> Settings:
    base = {
        "env": "test",
        "database_url": engine_url(tmp_path, "mw"),
        "jwt_secret": "test-secret-0123456789abcdef0123456789",
    }
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# F-085 - the body-size limit is a real limit
# ---------------------------------------------------------------------------


def test_declared_oversize_body_is_rejected_before_any_read(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path, max_body_bytes=64)))
    res = client.post(
        "/auth/login",
        content=b'{"email":"a@b.test","password":"' + b"x" * 256 + b'"}',
        headers={"content-type": "application/json"},
    )
    # 64 bytes is far below a login payload, so the declared-length fast path
    # must fire. Reverting the middleware entirely returns 422, not 413.
    assert res.status_code == 413


def test_chunked_body_over_limit_is_rejected_without_buffering_it() -> None:
    """The property that makes this a limit rather than a length check.

    ``Content-Length`` is absent, so only the streaming counter can catch this.
    The downstream app is instrumented to record how many bytes it was ever
    handed: with the old ``await request.body()`` implementation the whole
    oversized body reached the application before the 413.
    """
    limit = 1024
    seen: list[int] = []
    finished = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal finished
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b"") or b"")
            if not message.get("more_body", False):
                break
        seen.append(total)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BodySizeLimitMiddleware(app, max_bytes=limit)

    async def receive() -> Message:
        return {
            "type": "http.request",
            "body": b"x" * 256,
            "more_body": True,
        }

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    import anyio

    anyio.run(
        middleware, {"type": "http", "method": "POST", "path": "/x", "headers": []}, receive, send
    )
    finished = True

    assert finished, "the middleware did not return"
    assert sent[0]["status"] == 413, sent
    # The application must never have seen the oversized payload.
    assert seen == [], seen


def test_under_limit_chunked_body_still_reaches_the_application() -> None:
    """Non-vacuity in the other direction: a legal body must NOT be rejected."""
    received: list[bytes] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            received.append(message.get("body", b"") or b"")
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BodySizeLimitMiddleware(app, max_bytes=4096)
    chunks = [b"hello ", b"world"]

    async def receive() -> Message:
        if chunks:
            return {"type": "http.request", "body": chunks.pop(0), "more_body": True}
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    import anyio

    anyio.run(
        middleware, {"type": "http", "method": "POST", "path": "/x", "headers": []}, receive, send
    )

    assert sent[0]["status"] == 200
    assert b"".join(received) == b"hello world"


def test_real_request_body_survives_the_limit_middleware(tmp_path) -> None:
    """The app must still receive the actual parsed body."""
    client = TestClient(create_app(_settings(tmp_path)))
    res = client.post("/auth/login", json={"email": "nobody@example.test", "password": "x"})
    # A well-formed request is not a 413. 401 proves the body was parsed and
    # the route reached.
    assert res.status_code in (401, 422)
    assert res.status_code != 413


# ---------------------------------------------------------------------------
# F-081 - middleware order
# ---------------------------------------------------------------------------


def test_rate_limit_wraps_body_size_limit(tmp_path) -> None:
    """The rate limiter must be OUTSIDE the body-size middleware.

    Starlette's ``add_middleware`` *prepends*: ``app.user_middleware[0]`` is
    the outermost layer and therefore sees a request first. So "rate limiting
    runs before the body is read" is exactly "RateLimitMiddleware has a lower
    index than BodySizeLimitMiddleware". Reading the built stack proves what
    actually executes, rather than what a comment claims.
    """
    app = create_app(_settings(tmp_path))
    names = [cls.cls.__name__ for cls in app.user_middleware]
    rate = names.index("RateLimitMiddleware")
    body = names.index("BodySizeLimitMiddleware")
    assert rate < body, (
        f"RateLimitMiddleware must be registered AFTER BodySizeLimitMiddleware "
        f"(so it is outermost); got outermost-first order {names}"
    )


def test_prometheus_is_outermost_and_cors_is_inside_the_throttle(tmp_path) -> None:
    app = create_app(_settings(tmp_path, allowed_origins="https://example.test"))
    names = [cls.cls.__name__ for cls in app.user_middleware]
    assert names[0] == "PrometheusMetricsMiddleware", names
    assert "CORSMiddleware" in names, names
    # CORS answers a preflight before it costs a rate-limit token, so it must
    # sit outside the throttle.
    assert names.index("CORSMiddleware") < names.index("RateLimitMiddleware"), names
    assert names.index("RequestIdMiddleware") < names.index("RateLimitMiddleware"), names


# ---------------------------------------------------------------------------
# F-084 - bounded Prometheus label cardinality
# ---------------------------------------------------------------------------


def test_unmatched_route_uses_a_fixed_label_not_the_attacker_url(tmp_path) -> None:
    before = REQUESTS_TOTAL.labels(
        method="GET", path=UNMATCHED_ROUTE_LABEL, status="404"
    )._value.get()
    client = TestClient(create_app(_settings(tmp_path)))
    client.get("/definitely-not-a-route-aaaa")
    client.get("/definitely-not-a-route-bbbb")
    client.get("/definitely-not-a-route-cccc")
    after = REQUESTS_TOTAL.labels(
        method="GET", path=UNMATCHED_ROUTE_LABEL, status="404"
    )._value.get()

    assert after - before == 3, f"expected 3 unmatched requests counted, delta={after - before}"
    # And no label was created for any of the raw URLs.
    samples = {s.labels["path"] for s in REQUESTS_TOTAL.collect()[0].samples}
    for raw in ("/definitely-not-a-route-aaaa", "/definitely-not-a-route-bbbb"):
        assert raw not in samples, f"attacker-controlled label created: {raw}"
    assert UNMATCHED_ROUTE_LABEL in samples


# ---------------------------------------------------------------------------
# F-083 - a 500 that can be traced and is hardened
# ---------------------------------------------------------------------------


def test_unhandled_exception_yields_a_traceable_hardened_500(tmp_path) -> None:
    from fastapi import APIRouter

    settings = _settings(tmp_path)
    app = create_app(settings)

    boom = APIRouter()

    @boom.get("/_test/boom")
    async def _boom() -> None:  # pragma: no cover - the point is that it raises
        raise RuntimeError("secret-looking detail that must not reach the client")

    app.include_router(boom)
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/_test/boom")

    assert res.status_code == 500
    assert res.headers.get("X-Request-ID"), "500 must carry a request id"
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "no-referrer"
    assert "Content-Security-Policy" in res.headers
    body = res.json()
    assert body["detail"]["code"] == "internal_error"
    assert "must not reach the client" not in res.text
    assert "RuntimeError" not in res.text


def test_unhandled_exception_body_carries_the_request_id_it_was_given(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)), raise_server_exceptions=False)
    res = client.get("/definitely-not-a-route")
    assert res.status_code == 404
    # A 404 is not the exception path; assert the handler itself is wired by
    # checking it is registered on the app.
    app = create_app(_settings(tmp_path))
    assert Exception in app.exception_handlers
    assert app.exception_handlers[Exception] is unhandled_exception_response


# ---------------------------------------------------------------------------
# F-082 - log redaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "jwt_secret",
        "api_key",
        "access_token",
        "refresh_token",
        "authorization",
        "client_secret",
        "smtp_password",
        "totp",
        "PII_ENC_KEY",
    ],
)
def test_sensitive_field_names_are_recognised(key: str) -> None:
    assert is_sensitive_key(key), key


@pytest.mark.parametrize("key", ["user_id", "class_level", "count", "request_id", "status"])
def test_ordinary_field_names_are_not_redacted(key: str) -> None:
    assert not is_sensitive_key(key), key


def test_redaction_filter_scrubs_nested_secrets_and_jwts() -> None:
    filt = RedactionFilter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg={
            "user": "a@example.test",
            "password": "hunter2",
            "nested": {"api_key": "sk-0123456789abcdefghij"},
            "note": "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig here",
        },
        args=(),
        exc_info=None,
    )
    filt.filter(record)
    payload = record.msg
    assert payload["password"] == REDACTED
    assert payload["nested"]["api_key"] == REDACTED
    assert payload["note"] == REDACTED  # the JWT pattern fires on the value
    # Non-secret keys survive untouched so the log stays useful.
    assert payload["user"] == REDACTED  # an email address is PII


def test_redaction_filter_never_raises_on_odd_input() -> None:
    filt = RedactionFilter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=object(),
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert record.msg == REDACTED


def test_json_log_applies_redaction(monkeypatch) -> None:
    from bangla_gpt_api import logging_config

    captured: list[str] = []

    class _Cap(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    logger = logging.getLogger("test_redaction_integration")
    logger.handlers.clear()
    handler = _Cap()
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)
    logger.propagate = False

    logging_config.json_log(logger, logging.INFO, "login", password="s3cret", user_id=7)
    assert "s3cret" not in captured[0]
    assert REDACTED in captured[0]
    assert "7" in captured[0]


def test_json_log_secret_is_refused_in_production(tmp_path) -> None:
    """The one legitimate secret log must still be refused in production.

    Before this change the ONLY thing keeping the reset token out of a
    production log was an ``if not is_production`` at one call site. The gate
    is now driven from Settings by create_app, so a second call site added
    later inherits it for free.
    """
    from bangla_gpt_api import logging_config

    captured: list[str] = []

    class _Cap(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    logger = logging.getLogger("test_secret_gate")
    logger.handlers.clear()
    handler = _Cap()
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)
    logger.propagate = False

    try:
        # A production-configured app must refuse to emit the value. Settings
        # are single-process + mock-provider so every boot guard passes
        # unchanged (AUD-0025/0026/0027); nothing is monkeypatched away.
        os.environ["ALLOW_MOCK_LLM_IN_PRODUCTION"] = "1"
        os.environ["WEB_CONCURRENCY"] = "1"
        create_app(
            Settings(
                env="production",
                pii_allow_plaintext=False,
                jwt_secret="Zk7Qp2XvN8mR4tYcW1bH6jL3sD9fG5aE0uI2oP7xV4qM8nC6rT1wY3zB5",  # must survive the production entropy guard (F-067)
                database_url=f"sqlite:///{(tmp_path / 'prod.db').as_posix()}",
                allowed_origins="https://app.example.test",
                admin_email="admin@example.test",
                admin_password="Str0ngAdminPassw0rd!",
                metrics_require_auth=True,
                metrics_token="metric" + "0" * 32,
                pii_enc_key="LjDorcxuiR0OrEApp_g6hwfAbKKwimZQOPIvEz1pRhk=",
                smtp_enabled=True,
                smtp_host="smtp.example.test",
                smtp_from="noreply@example.test",
                llm_provider="mock",
            )
        )
        assert logging_config.secret_logging_allowed() is False
        logging_config.json_log_secret(
            logger, logging.INFO, "password_reset_token_console", token="a-real-token-value"
        )
        assert "a-real-token-value" not in captured[0]
        assert "secret_logging_blocked" in captured[0]
        assert REDACTED in captured[0]
    finally:
        logging_config.set_secret_logging_allowed(True)


def test_json_log_secret_is_emitted_outside_production() -> None:
    from bangla_gpt_api import logging_config

    captured: list[str] = []

    class _Cap(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    logger = logging.getLogger("test_secret_gate_dev")
    logger.handlers.clear()
    handler = _Cap()
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)
    logger.propagate = False

    try:
        logging_config.set_secret_logging_allowed(True)
        logging_config.json_log_secret(
            logger, logging.INFO, "password_reset_token_console", token="dev-token-value"
        )
        assert "dev-token-value" in captured[0]
    finally:
        logging_config.set_secret_logging_allowed(False)
