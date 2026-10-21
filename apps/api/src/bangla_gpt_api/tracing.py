"""Distributed tracing (I-03 / AUD-HI-04) — OpenTelemetry, environment-gated.

Three states, one switch each:

* ``TRACING_ENABLED=false`` (the default) — every entry point here is a no-op:
  no tracer provider, no instrumentation, no span objects. The call sites stay
  in the code, so enabling tracing never requires a code change.
* ``TRACING_ENABLED=true``, no endpoint — spans are created and dropped in
  process. The instrumentation is exercised (useful in tests and staging)
  and nothing leaves the host.
* ``TRACING_ENABLED=true`` with ``OTEL_EXPORTER_OTLP_ENDPOINT`` (or
  ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``) set — finished spans are batched to
  that collector. The endpoint is the only exported configuration this module
  reads directly; everything else is standard ``OTEL_*`` (see
  ``docs/operations/TRACING.md``).

Span shape for one tutoring request::

    POST /tutor/ask          server span (fastapi instrumentation, outermost)
      SELECT …               db spans (sqlalchemy instrumentation, per statement)
      llm.generate           manual span around the provider call

Log correlation: every structured log line emitted while a span is active
carries ``otel_trace_id`` and ``otel_span_id`` (see
``logging_config.json_log``), so a trace is reconstructible from the log sink
alone. The per-stage ``trace`` records keep their existing ``trace_id`` (the
request id), which the access line also carries.

Privacy (this is a minors-facing product): the ASGI instrumentation drops the
query string from ``http.url`` (a search box is free text) and captures no
headers; SQLAlchemy instrumentation never records statement parameters; manual
``span()`` attributes are filtered through the same key rules the log redactor
uses, so a future call site cannot accidentally export a credential.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import threading
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

#: Tracer name under which every span of this service is created.
TRACER_NAME = "bangla_gpt_api"

#: Health/scrape endpoints: high volume, no diagnostic value in a trace.
#: Regexes are matched against the full request URL (``re.search``).
EXCLUDED_URLS = "/health$,/live$,/metrics$"

#: ``TRACING_ENABLED`` is the master switch; the endpoint selects the sink.
_ENDPOINT_ENV_VARS = ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT")

#: Values of OTEL_SDK_DISABLED that mean "do not start the SDK at all".
_TRUTHY = frozenset({"1", "true", "yes", "on"})

_provider: Any = None
_active = False
_otlp_attached = False
_sqlalchemy_instrumented = False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def otlp_endpoint() -> str | None:
    """The configured OTLP traces endpoint, or None (no export)."""
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() in _TRUTHY:
        return None
    for name in _ENDPOINT_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def tracing_active() -> bool:
    """True when spans are being recorded in this process."""
    return _active


def configure_tracing(settings: object) -> bool:
    """Install the tracer provider once per process.

    Called from ``initialize.observability`` on every app build; idempotent.
    Returns True when spans are recorded, False for the no-op state. Never
    raises: a tracing misconfiguration must not keep the tutor offline.
    """
    global _active
    if not bool(getattr(settings, "tracing_enabled", False)):
        _active = False
        return False
    try:
        _build_provider(settings)
    except Exception:  # noqa: BLE001 - tracing must degrade, never fail the app
        logger.warning("tracing_init_failed", exc_info=True)
        _active = False
        return False
    _active = True
    _export(settings)
    return True


def _build_provider(settings: object) -> None:
    global _provider
    if _provider is not None:
        return
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME")
            or str(getattr(settings, "app_name", TRACER_NAME)),
            "service.version": str(getattr(settings, "version", "unknown")),
            "deployment.environment": str(getattr(settings, "env", "unknown")),
        }
    )
    _provider = TracerProvider(resource=resource, sampler=_build_sampler())


def _build_sampler() -> Any:
    """Sampler from the standard OTEL_* variables.

    Default is ``parentbased_always_on``: a request that arrives without a
    parent trace is sampled, and a child honours its parent's decision. A
    ratio is available for staging/production volume control via
    ``OTEL_TRACES_SAMPLER=parentbased_traceidratio`` plus
    ``OTEL_TRACES_SAMPLER_ARG=<0..1>``; an unrecognised value falls back to
    the default rather than disabling tracing silently.
    """
    from opentelemetry.sdk.trace.sampling import (
        ALWAYS_OFF,
        ALWAYS_ON,
        ParentBased,
        TraceIdRatioBased,
    )

    name = os.environ.get("OTEL_TRACES_SAMPLER", "").strip().lower()
    if name == "always_off":
        return ALWAYS_OFF
    if name == "always_on":
        return ALWAYS_ON
    if name in ("traceidratio", "parentbased_traceidratio"):
        try:
            ratio = float(os.environ.get("OTEL_TRACES_SAMPLER_ARG", "1.0"))
        except ValueError:
            ratio = 1.0
        ratio = min(max(ratio, 0.0), 1.0)
        sampler = TraceIdRatioBased(ratio)
        return ParentBased(sampler) if name.startswith("parentbased") else sampler
    return ParentBased(ALWAYS_ON)


def _export(settings: object) -> None:
    """Attach the OTLP batch processor when an endpoint is configured."""
    global _otlp_attached
    if _otlp_attached:
        return
    endpoint = otlp_endpoint()
    if endpoint is None:
        logger.info(
            "tracing_enabled_without_endpoint: spans are recorded and dropped; "
            "set OTEL_EXPORTER_OTLP_ENDPOINT to export"
        )
        return
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        if _provider is None:  # pragma: no cover - defensive; _build_provider ran
            return
        _provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=endpoint),
                # Small batches: a decisive flush on a mostly-idle staging host
                # is worth more than batching efficiency (defaults: 5 s/512).
                schedule_delay_millis=5000,
            )
        )
    except Exception:  # noqa: BLE001 - exporter/collector problems are not app problems
        logger.warning("tracing_exporter_init_failed", exc_info=True)
        return
    _otlp_attached = True
    logger.info("tracing_export_enabled: %s", endpoint)


def add_span_exporter(exporter: Any) -> None:
    """Attach a span exporter (test/verification seam).

    Not used in production paths; the OTLP processor above is. Kept here so a
    test can assert on real spans with an ``InMemorySpanExporter`` without a
    collector, which is what the I-03 verification does.
    """
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    _build_provider(_SettingsStub())
    _provider.add_span_processor(SimpleSpanProcessor(exporter))


class _SettingsStub:
    """Minimal settings stand-in for exporter attachment before app build."""

    app_name = TRACER_NAME
    version = "unknown"
    env = "unknown"


# ---------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------


def instrument_app(app: Any) -> bool:
    """Wrap a FastAPI app in server spans (outermost; no-op when off)."""
    if not _active or _provider is None:
        return False
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=_provider,
            server_request_hook=_scrub_request_span,
            excluded_urls=EXCLUDED_URLS,
            # The ASGI send/receive spans are one span per SSE chunk on the
            # chat path; the trace records and the RAG histograms already
            # carry per-stage timing, so keeping them would be volume without
            # a question they answer.
            exclude_spans=["send", "receive"],
        )
    except Exception:  # noqa: BLE001
        logger.warning("tracing_app_instrument_failed", exc_info=True)
        return False
    return True


def instrument_engine(engine: Any) -> bool:
    """Attach DB statement spans to one engine (no-op when off).

    Tries ``opentelemetry-instrumentation-sqlalchemy`` first. As of
    instrumentation 0.66b1 that package declares ``sqlalchemy >=1.0,<2.1`` and
    silently declines the SQLAlchemy 2.1 installed here (it logs and attaches
    nothing), so the fallback below is what produces DB spans today: the same
    engine-level events the instrumentor itself uses, with the same attribute
    names. When an instrumentor release accepts SQLAlchemy 2.1, the first
    branch starts producing the spans and the fallback stops being reached.
    """
    global _sqlalchemy_instrumented
    if not _active or _provider is None:
        return False
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        instrumentor = SQLAlchemyInstrumentor()
        if _sqlalchemy_instrumented:
            # The upstream instrumentor is process-global; a second engine
            # (a test building another app, or a worker with two engines)
            # would otherwise be attached to nothing. Detaching first drops
            # the previous engine's listeners, which is the documented cost.
            instrumentor.uninstrument()
        instrumentor.instrument(engine=engine, tracer_provider=_provider)
        if getattr(instrumentor, "_is_instrumented_by_opentelemetry", False):
            _sqlalchemy_instrumented = True
            return True
    except Exception:  # noqa: BLE001 - never break the app for a span
        logger.warning("tracing_db_instrument_failed", exc_info=True)
        return False
    try:
        _attach_engine_events(engine)
    except Exception:  # noqa: BLE001
        logger.warning("tracing_db_events_failed", exc_info=True)
        return False
    return True


#: Open engine spans, keyed by cursor id. The cursor object is alive between
#: ``before_cursor_execute`` and ``after_cursor_execute``, so its identity is a
#: stable key; the lock covers the (rare) multi-threaded sync route pool.
_engine_spans: dict[int, Any] = {}
_engine_spans_lock = threading.Lock()

#: Statements are recorded with string literals replaced: SQL text is useful
#: in a trace, an inline student question or email address is not.
_STATEMENT_LITERAL = re.compile(r"'[^']*'")
_STATEMENT_MAX = 300


def _statement_name(statement: str) -> str:
    """``"SELECT"`` / ``"INSERT"`` / ``"CREATE"`` — the operation, not the SQL."""
    head = statement.strip().split(None, 1)
    operation = head[0].upper() if head else "SQL"
    return operation if operation.isidentifier() else "SQL"


def _scrubbed_statement(statement: str) -> str:
    return _STATEMENT_LITERAL.sub("'?'", statement)[:_STATEMENT_MAX]


def _attach_engine_events(engine: Any) -> None:
    """Create a span per statement from SQLAlchemy's execution events."""
    from opentelemetry.trace import Status, StatusCode
    from sqlalchemy import event

    tracer = _provider.get_tracer(TRACER_NAME)
    db_system = str(getattr(getattr(engine, "dialect", None), "name", "sql"))

    # SQLAlchemy passes the listener arguments positionally; the names below
    # only document the signature, and the unused ones carry a leading
    # underscore so the dead-code gate does not read them as mistakes.
    def before_cursor_execute(  # noqa: PLR0913 - SQLAlchemy event signature
        _conn: Any,
        cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        executemany: bool,
    ) -> None:
        attributes = {
            "db.system": db_system,
            "db.operation": _statement_name(statement),
            "db.statement": _scrubbed_statement(statement),
            "db.executemany": bool(executemany),
        }
        span = tracer.start_span(_statement_name(statement), attributes=attributes)
        with _engine_spans_lock:
            _engine_spans[id(cursor)] = span

    def after_cursor_execute(  # noqa: PLR0913 - SQLAlchemy event signature
        _conn: Any,
        cursor: Any,
        _statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        with _engine_spans_lock:
            span = _engine_spans.pop(id(cursor), None)
        if span is not None:
            span.end()

    def handle_error(exception_context: Any) -> None:
        cursor = getattr(exception_context, "cursor", None)
        if cursor is None:
            return
        with _engine_spans_lock:
            span = _engine_spans.pop(id(cursor), None)
        if span is None:
            return
        try:
            span.record_exception(exception_context.original_exception)
            span.set_status(Status(StatusCode.ERROR))
        finally:
            span.end()

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    event.listen(engine, "handle_error", handle_error)


def _scrub_request_span(span: Any, scope: dict) -> None:
    """Server-request hook: keep free text out of the span.

    ``http.url`` is the only attribute instrumentation-asgi adds that can carry
    user input (the query string). ``/search?q=…`` would otherwise put a
    student's wording into a trace; the parameterised route template in
    ``http.target`` already answers "which endpoint" without it.
    """
    with contextlib.suppress(Exception):  # hook must never break a request
        if not span.is_recording():
            return
        for key in ("http.url", "url.full"):
            url = span.attributes.get(key) if span.attributes else None
            if isinstance(url, str) and "?" in url:
                span.set_attribute(key, url.split("?", 1)[0])


# ---------------------------------------------------------------------------
# Manual spans
# ---------------------------------------------------------------------------


def _clean_attributes(fields: dict[str, Any]) -> dict[str, Any]:
    """Keep primitive, non-sensitive attributes only.

    Uses the log redactor's key rules (``logging_config.is_sensitive_key``) so
    "never put a credential on a span" is one control, not a promise.
    """
    from bangla_gpt_api.logging_config import is_sensitive_key

    out: dict[str, Any] = {}
    for key, value in fields.items():
        if not isinstance(key, str) or value is None or is_sensitive_key(key):
            continue
        if isinstance(value, (bool, int, float, str)):
            out[key] = value
        elif isinstance(value, (list, tuple)) and all(
            isinstance(item, (bool, int, float, str)) for item in value
        ):
            out[key] = list(value)
    return out


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start a span around a block; yields None when tracing is off.

    >>> with span("llm.generate", model="mock") as current:  # doctest: +SKIP
    ...     ...
    """
    if not _active or _provider is None:
        yield None
        return
    tracer = _provider.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(name, attributes=_clean_attributes(attributes)) as current:
        yield current


def set_attributes(current: Any, **attributes: Any) -> None:
    """Add attributes to an existing span (silently ignores a None span)."""
    if current is None:
        return
    with contextlib.suppress(Exception):
        current.set_attributes(_clean_attributes(attributes))


def current_trace_ids() -> tuple[str | None, str | None]:
    """``(trace_id, span_id)`` of the active span, hex, or (None, None).

    Called by ``logging_config.json_log`` for trace-log correlation.
    """
    if not _active:
        return (None, None)
    try:
        from opentelemetry import trace as otel_trace

        context = otel_trace.get_current_span().get_span_context()
    except Exception:  # noqa: BLE001 - correlation is best-effort
        return (None, None)
    if context is None or not context.is_valid:
        return (None, None)
    return (format(context.trace_id, "032x"), format(context.span_id, "016x"))
