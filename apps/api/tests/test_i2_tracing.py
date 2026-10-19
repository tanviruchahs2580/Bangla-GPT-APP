"""I-03 (AUD-HI-04): OpenTelemetry spans, trace-log correlation, and the switch.

The exporter is attached to the same tracer provider the app uses, so these
tests assert on spans the production wiring produced — the FastAPI server span,
the SQLAlchemy statement spans, the tutor's ``llm.generate`` span and the
``ai_job.run`` worker span — not on a hand-built trace. The off state is
asserted the same way: an app built with ``TRACING_ENABLED`` unset produces no
span at all.

Bengali literals are Unicode escapes only (house rule for API tests).
"""

import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from bangla_gpt_api import tracing
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JWT_SECRET = "test-secret-0123456789abcdef0123456789"
# "kosh ki?" -- a class-6 science corpus question the sample index answers.
GROUNDED_QUESTION = "\u0995\u09cb\u09b7 \u0995\u09c0?"
CHAPTER = "\u0995\u09cb\u09b7"
# A free-text search term; it must never reach a span attribute.
SEARCH_TEXT = "\u0986\u09b2\u09cb\u0997\u09c1\u09a8 \u0995\u09c0?"


@pytest.fixture(autouse=True)
def _tracing_state_is_restored():
    """Leave the process in the no-op state other test modules expect."""
    yield
    tracing.configure_tracing(SimpleNamespace(tracing_enabled=False))


def _settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "env": "test",
        "database_url": f"sqlite:///{tmp_path.as_posix()}/i2-tracing.db",
        "jwt_secret": JWT_SECRET,
        "admin_email": None,
        "admin_password": None,
    }
    base.update(overrides)
    return Settings(**base)


def _client(tmp_path: Path, *, tracing_on: bool) -> TestClient:
    app = create_app(_settings(tmp_path, tracing_enabled=tracing_on))
    return TestClient(app)


def _register(client: TestClient, email: str = "student@example.com") -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Student",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _names(spans) -> set[str]:
    return {span.name for span in spans}


def _attribute_values(spans) -> str:
    return json.dumps(
        [
            {key: value for key, value in span.attributes.items()}
            for span in spans
            if span.attributes
        ],
        default=str,
    )


class _Collector(logging.Handler):
    """Collect raw log lines from one named logger."""

    def __init__(self, logger_name: str) -> None:
        super().__init__()
        self.messages: list[str] = []
        self._logger = logging.getLogger(logger_name)

    def __enter__(self) -> "_Collector":
        self._logger.addHandler(self)
        return self

    def __exit__(self, *exc: object) -> None:
        self._logger.removeHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def payloads(self, event: str) -> list[dict]:
        out: list[dict] = []
        for message in self.messages:
            try:
                parsed = json.loads(message)
            except ValueError:
                continue
            if parsed.get("event") == event:
                out.append(parsed)
        return out


# --- one request, four span families, one trace ----------------------------


def test_ask_produces_server_db_and_llm_spans_in_one_trace(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    client = _client(tmp_path, tracing_on=True)
    tracing.add_span_exporter(exporter)
    headers = _register(client)

    res = client.post(
        "/tutor/ask",
        json={"question": GROUNDED_QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text

    spans = exporter.get_finished_spans()
    names = _names(spans)
    assert "POST /tutor/ask" in names, names
    assert "llm.generate" in names, names

    server = next(s for s in spans if s.name == "POST /tutor/ask")
    server_trace = server.context.trace_id
    # Scope to the ask trace: registration and login are traced too.
    ask_spans = [s for s in spans if s.context.trace_id == server_trace]
    ask_names = _names(ask_spans)
    assert {"SELECT", "INSERT"} & ask_names, ask_names
    assert server.attributes["http.route"] == "/tutor/ask"
    assert server.attributes["http.method"] == "POST"
    assert server.attributes["http.status_code"] == 200

    llm = next(s for s in ask_spans if s.name == "llm.generate")
    assert llm.attributes["llm.model"]
    assert llm.attributes["llm.provider"]

    db = next(s for s in ask_spans if s.name in ("SELECT", "INSERT"))
    assert db.attributes["db.system"] == "sqlite"
    assert db.attributes["db.operation"] in ("SELECT", "INSERT")

    # One trace: the DB and LLM spans are descendants of the server span.
    assert llm.parent is not None and llm.parent.span_id == server.context.span_id
    assert db.parent is not None and db.parent.span_id == server.context.span_id


def test_job_worker_span_covers_a_detached_generation_job(tmp_path: Path) -> None:
    """The Create-hub worker runs off the request; it gets its own span."""
    exporter = InMemorySpanExporter()
    app = create_app(_settings(tmp_path, tracing_enabled=True))
    tracing.add_span_exporter(exporter)
    with TestClient(app) as client:
        res = client.post(
            "/auth/register",
            json={
                "email": "teach@example.com",
                "password": PASSWORD,
                "name": "Teacher",
                "role": "teacher",
            },
        )
        assert res.status_code == 201, res.text
        login = client.post(
            "/auth/login", json={"email": "teach@example.com", "password": PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        queued = client.post(
            "/teacher/jobs",
            json={
                "kind": "worksheet",
                "payload": {"class_level": 6, "subject": "science", "chapter": CHAPTER},
            },
            headers=headers,
        )
        assert queued.status_code == 202, queued.text
        job_id = queued.json()["id"]

        deadline = time.monotonic() + 20.0
        status = queued.json()["status"]
        while time.monotonic() < deadline and status not in ("ready", "failed", "dead_letter"):
            status = client.get(f"/teacher/jobs/{job_id}", headers=headers).json()["status"]
            time.sleep(0.05)
        assert status == "ready", f"job did not run: {status}"

    assert "ai_job.run" in _names(exporter.get_finished_spans())


# --- the off switch --------------------------------------------------------


def test_tracing_disabled_produces_no_spans_and_no_instrumentation(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    client = _client(tmp_path, tracing_on=False)
    tracing.add_span_exporter(exporter)  # attached, but nothing is instrumented
    headers = _register(client)

    assert (
        client.post(
            "/tutor/ask",
            json={"question": GROUNDED_QUESTION, "class_level": 6, "subject": "science"},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.get("/health").status_code == 200

    assert exporter.get_finished_spans() == ()
    assert tracing.tracing_active() is False
    assert tracing.instrument_app(object()) is False
    with tracing.span("nothing") as current:
        assert current is None


def test_span_is_a_noop_context_when_disabled(tmp_path: Path) -> None:
    tracing.configure_tracing(SimpleNamespace(tracing_enabled=False))
    with tracing.span("x", model="mock") as current:
        assert current is None


# --- export gating ---------------------------------------------------------


def test_otlp_export_requires_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """No endpoint, no exporter: spans are recorded and dropped."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    assert tracing.otlp_endpoint() is None

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    assert tracing.otlp_endpoint() == "http://collector:4318"

    # The standard kill switch turns the SDK off entirely.
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert tracing.otlp_endpoint() is None


def test_tracing_without_settings_flag_is_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    assert (
        tracing.configure_tracing(SimpleNamespace(tracing_enabled=False)) is False
    )  # endpoint alone never turns tracing on
    assert tracing.tracing_active() is False


# --- privacy ---------------------------------------------------------------


def test_query_string_never_reaches_a_span(tmp_path: Path) -> None:
    """Free-text search must not travel on ``http.url``."""
    exporter = InMemorySpanExporter()
    client = _client(tmp_path, tracing_on=True)
    tracing.add_span_exporter(exporter)
    headers = _register(client)

    res = client.get(f"/search?q={SEARCH_TEXT}", headers=headers)
    assert res.status_code == 200, res.text

    spans = exporter.get_finished_spans()
    assert spans, "the search request must be traced"
    dumped = _attribute_values(spans)
    assert SEARCH_TEXT not in dumped
    for span in spans:
        url = span.attributes.get("http.url") if span.attributes else None
        if isinstance(url, str):
            assert "?" not in url, url


def test_span_attributes_drop_sensitive_keys_and_none() -> None:
    tracing.configure_tracing(SimpleNamespace(tracing_enabled=False))
    exporter = InMemorySpanExporter()
    tracing.add_span_exporter(exporter)
    tracing.configure_tracing(
        SimpleNamespace(tracing_enabled=True, app_name="t", version="0", env="test")
    )

    with tracing.span(
        "check", model="mock", missing=None, api_key="sk-secret", token="abc", count=3
    ):
        pass

    (span,) = exporter.get_finished_spans()
    assert span.attributes == {"model": "mock", "count": 3}


def test_statement_literals_are_scrubbed() -> None:
    statement = "SELECT * FROM users WHERE email = 'child@example.com' AND id = 7"
    scrubbed = tracing._scrubbed_statement(statement)
    assert "child@example.com" not in scrubbed
    assert scrubbed == "SELECT * FROM users WHERE email = '?' AND id = 7"
    assert tracing._statement_name(statement) == "SELECT"


def test_no_pii_in_spans_from_a_tutor_request(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    client = _client(tmp_path, tracing_on=True)
    tracing.add_span_exporter(exporter)
    headers = _register(client, "pii@example.com")
    client.post(
        "/tutor/ask",
        json={"question": GROUNDED_QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )

    dumped = _attribute_values(exporter.get_finished_spans())
    assert GROUNDED_QUESTION not in dumped
    assert "pii@example.com" not in dumped
    # Keys, not values: db.statement legitimately names a column such as
    # users.password_hash, and the hash itself never appears.
    keys = {
        key.lower() for span in exporter.get_finished_spans() for key in (span.attributes or {})
    }
    assert not any(
        forbidden in attribute_key
        for attribute_key in keys
        for forbidden in ("password", "authorization", "token")
    ), keys


# --- trace-log correlation -------------------------------------------------


def test_access_log_carries_the_ids_of_the_request_span(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    client = _client(tmp_path, tracing_on=True)
    tracing.add_span_exporter(exporter)
    headers = _register(client, "corr@example.com")

    with _Collector("bangla_gpt_api.access") as collector:
        assert client.get("/users/me", headers=headers).status_code == 200

    (line,) = collector.payloads("access")
    spans = exporter.get_finished_spans()
    trace_ids = {format(span.context.trace_id, "032x") for span in spans}
    span_ids = {format(span.context.span_id, "016x") for span in spans}
    assert line["otel_trace_id"] in trace_ids, line
    assert line["otel_span_id"] in span_ids, line
    # The existing request-scoped correlation id is untouched.
    assert line["trace_id"] == line["request_id"]


def test_health_and_metrics_are_not_traced(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    client = _client(tmp_path, tracing_on=True)
    tracing.add_span_exporter(exporter)

    assert client.get("/health").status_code == 200
    assert client.get("/live").status_code == 200
    assert client.get("/metrics").status_code == 200

    assert _names(exporter.get_finished_spans()) == set()
