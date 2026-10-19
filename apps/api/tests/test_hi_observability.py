"""HI observability fixes: access log (I-01), business metrics (I-02),
per-stage trace records (I-03) and SSE proxy headers (H-16).

Each test fails on the pre-fix code:

* no ``access`` line existed at all, and no user handle was logged;
* ``bgpt_ai_answers_total`` / ``bgpt_ai_tokens_total`` /
  ``bgpt_ai_cost_usd_total`` / ``bgpt_ai_jobs_total`` were not exported, so no
  dashboard or alert could reference them;
* no ``trace`` records existed (tracing is off by default and there was
  nothing behind the flag);
* the SSE response carried no ``X-Accel-Buffering`` / ``Cache-Control``.

Bengali literals are Unicode escapes only (house rule for API tests).
"""

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from sqlalchemy import text

from bangla_gpt_api import metrics
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.costs import record_ai_usage

PASSWORD = "supersecret1"
JWT_SECRET = "test-secret-0123456789abcdef0123456789"
# "kosh ki?" -- a class-6 science corpus question the sample index answers.
GROUNDED_QUESTION = "\u0995\u09cb\u09b7 \u0995\u09c0?"
# An out-of-corpus question: must be refused by the coverage gate.
OUT_OF_CORPUS_QUESTION = (
    "\u0997\u09a4 \u09ac\u09bf\u09b6\u09cd\u09ac\u0995\u09be\u09aa "
    "\u09ab\u09c1\u099f\u09ac\u09b2 \u09ab\u09be\u0987\u09a8\u09be\u09b2\u09c7 "
    "\u0995\u09cb\u09a8 \u09a6\u09b2 \u099c\u09bf\u09a4\u09c7\u099b\u09bf\u09b2?"
)


class _Collector(logging.Handler):
    """Collect raw log lines from one named logger."""

    def __init__(self, logger_name: str) -> None:
        super().__init__()
        self.logger_name = logger_name
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


def _settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "env": "test",
        "database_url": f"sqlite:///{tmp_path}/hi-observability.db",
        "jwt_secret": JWT_SECRET,
    }
    base.update(overrides)
    return Settings(**base)


def _client(tmp_path: Path, **overrides) -> TestClient:
    return TestClient(create_app(_settings(tmp_path, **overrides)))


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


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


# --- I-02: business metrics exist in the exported registry -----------------


def test_business_metric_names_are_rendered_by_the_registry() -> None:
    rendered = generate_latest(metrics.REGISTRY).decode("utf-8")
    for name in (
        "bgpt_ai_answers_total",
        "bgpt_ai_tokens_total",
        "bgpt_ai_cost_usd_total",
        "bgpt_ai_jobs_total",
    ):
        assert f"# HELP {name} " in rendered, f"{name} is not exported"


def test_ai_budget_gauge_reports_zero_until_configured() -> None:
    """The gauge is always exported; 0 means "not configured".

    An alert rule cannot reference a series that may not exist, so the
    burn-rate rule gates on ``> 0`` instead (see alerts.yml).
    """
    metrics.set_ai_budget_usd(0)
    rendered = generate_latest(metrics.REGISTRY).decode("utf-8")
    assert "bgpt_ai_monthly_budget_usd 0.0" in rendered
    try:
        metrics.set_ai_budget_usd(250.0)
        rendered = generate_latest(metrics.REGISTRY).decode("utf-8")
        assert "bgpt_ai_monthly_budget_usd 250.0" in rendered
    finally:
        metrics.set_ai_budget_usd(0)


def test_answer_counter_folds_unknown_labels_into_other() -> None:
    before = _counter_value(metrics.AI_ANSWERS_TOTAL, route="other", outcome="other")
    metrics.record_tutor_answer("not-a-route", "not-an-outcome")
    assert _counter_value(metrics.AI_ANSWERS_TOTAL, route="other", outcome="other") == before + 1


def test_ask_increments_answered_and_refused_counters(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = _register(client)
    answered_before = _counter_value(metrics.AI_ANSWERS_TOTAL, route="tutor", outcome="answered")
    refused_before = _counter_value(metrics.AI_ANSWERS_TOTAL, route="tutor", outcome="refused")

    grounded = client.post(
        "/tutor/ask",
        json={"question": GROUNDED_QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert grounded.status_code == 200, grounded.text
    assert grounded.json()["grounded"] is True

    refused = client.post(
        "/tutor/ask",
        json={"question": OUT_OF_CORPUS_QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert refused.status_code == 200, refused.text
    assert refused.json()["grounded"] is False

    assert (
        _counter_value(metrics.AI_ANSWERS_TOTAL, route="tutor", outcome="answered")
        == answered_before + 1
    )
    assert (
        _counter_value(metrics.AI_ANSWERS_TOTAL, route="tutor", outcome="refused")
        == refused_before + 1
    )


def test_usage_ledger_exports_tokens_and_cost(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    prompt_tokens_before = _counter_value(
        metrics.AI_TOKENS_TOTAL, model="gemini-3.1-flash-lite", direction="prompt"
    )
    cost_before = _counter_value(
        metrics.AI_COST_USD_TOTAL, model="gemini-3.1-flash-lite", route="tutor.ask"
    )

    with factory() as session:
        session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, role, created_at)"
                " VALUES (1, 'ledger@example.com', 'x', 'student', '2026-01-01 00:00:00')"
            )
        )
        row = record_ai_usage(
            session,
            user_id=1,
            route="tutor.ask",
            model="gemini-3.1-flash-lite",
            prompt_text="x" * 400,
            answer_text="y" * 80,
        )
        session.commit()
        assert row.prompt_tokens == 100
        assert row.completion_tokens == 20

    assert (
        _counter_value(metrics.AI_TOKENS_TOTAL, model="gemini-3.1-flash-lite", direction="prompt")
        == prompt_tokens_before + 100
    )
    cost_after = _counter_value(
        metrics.AI_COST_USD_TOTAL, model="gemini-3.1-flash-lite", route="tutor.ask"
    )
    # 100 prompt tokens * $0.00025/1K + 20 completion * $0.0015/1K.
    assert cost_after == pytest.approx(cost_before + 0.000025 + 0.00003, rel=1e-9)


# --- I-01: one structured access line per request --------------------------


def test_access_log_has_route_status_latency_and_pseudonymous_user(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = _register(client, "access@example.com")

    with _Collector("bangla_gpt_api.access") as collector:
        assert client.get("/health").status_code == 200
        assert client.get("/users/me", headers=headers).status_code == 200

    lines = collector.payloads("access")
    assert len(lines) == 2, collector.messages
    health, me = lines
    assert health["op"] == "http_request"
    assert health["route"] == "/health"
    assert health["status"] == 200
    assert isinstance(health["latency_ms"], (int, float))
    assert health["request_id"], "the access line must carry the request id"
    assert me["route"] == "/users/me"
    assert me["user_ref"].startswith("u_")
    # Pseudonymous: the handle is not the user id, and no identity leaks.
    assert me["user_ref"] != "u_1" and me["user_ref"] != "1"
    assert "access@example.com" not in "\n".join(collector.messages)


def test_access_log_is_stable_per_user_and_can_be_disabled(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = _register(client, "stable@example.com")
    with _Collector("bangla_gpt_api.access") as collector:
        client.get("/users/me", headers=headers)
        client.get("/users/me", headers=headers)
    refs = {line["user_ref"] for line in collector.payloads("access")}
    assert len(refs) == 1

    quiet = _client(tmp_path, access_log_enabled=False)
    quiet_headers = _register(quiet, "quiet@example.com")
    with _Collector("bangla_gpt_api.access") as collector:
        assert quiet.get("/users/me", headers=quiet_headers).status_code == 200
    assert collector.payloads("access") == []


# --- I-03: a trace record per pipeline stage -------------------------------


def test_ask_emits_retrieval_and_generation_trace_records(tmp_path: Path) -> None:
    client = _client(tmp_path, tracing_enabled=True)
    headers = _register(client, "trace@example.com")

    with _Collector("bangla_gpt_api.trace") as collector:
        res = client.post(
            "/tutor/ask",
            json={"question": GROUNDED_QUESTION, "class_level": 6, "subject": "science"},
            headers=headers,
        )
        assert res.status_code == 200, res.text

    records = collector.payloads("trace")
    stages = {record["stage"] for record in records}
    assert {"retrieval", "generation"} <= stages, records

    retrieval = next(r for r in records if r["stage"] == "retrieval")
    assert retrieval["trace_id"], "a trace id must tie the stages together"
    assert retrieval["index_version"], "the trace must name the corpus index"
    assert retrieval["retrieved_ids"], "retrieved chunk ids are the point of the record"
    assert retrieval["gate"] in ("pass", "refuse")

    generation = next(r for r in records if r["stage"] == "generation")
    assert generation["trace_id"] == retrieval["trace_id"]
    # A5-02 registry contract: the trace value is "<id>@<semver>+sp-<digest>"
    # (e.g. tutor_system@1.0.1+sp-...), not the bare digest the inline prompt
    # constant used to carry; the digest half still pins the exact text.
    assert generation["prompt_version"].startswith("tutor_system@")
    assert "+sp-" in generation["prompt_version"]
    assert generation["prompt_tokens"] > 0
    assert generation["completion_tokens"] > 0
    assert generation["model"], "the model that answered must be in the trace"


def test_trace_records_are_absent_when_disabled(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = _register(client, "notrace@example.com")
    with _Collector("bangla_gpt_api.trace") as collector:
        client.post(
            "/tutor/ask",
            json={"question": GROUNDED_QUESTION, "class_level": 6, "subject": "science"},
            headers=headers,
        )
    assert collector.payloads("trace") == []


# --- H-16: SSE responses tell proxies not to buffer ----------------------


def test_sse_stream_declares_no_buffering_and_no_cache(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = _register(client, "sse@example.com")
    conv = client.post("/tutor/conversations", json={}, headers=headers)
    assert conv.status_code == 201, conv.text
    conversation_id = conv.json()["id"]

    with client.stream(
        "POST",
        f"/tutor/conversations/{conversation_id}/messages/stream",
        json={"message": GROUNDED_QUESTION},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        assert "no-cache" in response.headers["cache-control"]
        assert response.headers["x-request-id"]
        # Consume the stream so the response is fully closed.
        list(response.iter_lines())
