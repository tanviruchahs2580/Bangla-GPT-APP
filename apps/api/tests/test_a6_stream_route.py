"""A6-08/AUD-A2-16: the streaming contract reaches the SSE wire.

The service-side contract (token / citation / heartbeat / error / final) is
pinned in tests/test_rag2_streaming_contract.py. What the audit found missing
was the TRANSPORT half: routers/tutor.py forwarded only token and the final
response, so heartbeat and citation never reached the client
(handoff: .audit/handoffs/api-rag2.md, section 1). These tests drive the real
`POST /tutor/conversations/{id}/messages/stream` route and assert on the raw
SSE text:

* a slow provider produces `event: heartbeat` frames (not a silent socket),
* a grounded answer produces `event: citation` (validated sources) BEFORE the
  final `event: done`,
* an injected mid-stream failure produces `event: error` and NO `done`, and
  the user turn is persisted while no partial assistant row is (the documented
  partial-answer persistence semantics);
* a tripped circuit with no fallback degrades to the evidence-only answer:
  `event: error` + the degraded token + `event: done` with grounded=false.

Bengali literals are Unicode escapes only (repo rule for new files).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.providers.mock import MockLLMProvider

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
QUESTION = "\u0995\u09cb\u09b7 \u0995\u09c0?"  # "kosh ki?"


class _SlowMock:
    """Mock output, throttled so the heartbeat interval fires."""

    name = "slow-mock"
    supports_vision = False
    supports_sampling = False

    def __init__(self, delay: float = 0.05) -> None:
        self.inner = MockLLMProvider()
        self.delay = delay

    async def generate(self, prompt, *, system=None, **kwargs):
        return await self.inner.generate(prompt, system=system)

    async def stream(self, prompt, *, system=None, **kwargs) -> AsyncIterator[str]:
        text = await self.inner.generate(prompt, system=system)
        for i in range(0, len(text), 24):
            await asyncio.sleep(self.delay)
            yield text[i : i + 24]


class _FailsMidStream:
    """Yields one delta, then the provider dies (mid-stream failure)."""

    name = "mid-fail"
    supports_vision = False
    supports_sampling = False

    def __init__(self, first: str = "\u09aa\u09cd\u09b0\u09a5\u09ae ") -> None:
        self.first = first

    async def generate(self, prompt, *, system=None, **kwargs):
        raise ProviderError("upstream down")

    async def stream(self, prompt, *, system=None, **kwargs) -> AsyncIterator[str]:
        yield self.first
        raise ProviderError("upstream died mid-stream")


def _app(monkeypatch, tmp_path, provider, db_name: str, **env) -> TestClient:
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    monkeypatch.setattr("bangla_gpt_api.main.get_fast_provider", lambda s: provider)
    settings = Settings(
        env="test", database_url=f"sqlite:///{tmp_path}/{db_name}", jwt_secret=SECRET
    )
    return TestClient(create_app(settings))


def _register_login(client: TestClient, email: str) -> dict[str, str]:
    body = {
        "email": email,
        "password": PASSWORD,
        "name": "\u09b6\u09bf\u0995\u09cd\u09b7\u09be\u09b0\u09cd\u09a5\u09c0",
        "role": "student",
        "class_level": 6,
        "guardian_consent": True,
    }
    assert client.post("/auth/register", json=body).status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _stream(client: TestClient, headers: dict[str, str]) -> str:
    conv = client.post("/tutor/conversations", json={}, headers=headers)
    assert conv.status_code == 201, conv.text
    res = client.post(
        f"/tutor/conversations/{conv.json()['id']}/messages/stream",
        json={"message": QUESTION},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.text


def _event_names(body: str) -> list[str]:
    return [
        line.removeprefix("event: ") for line in body.splitlines() if line.startswith("event: ")
    ]


def _data_after(body: str, event: str) -> dict:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line == f"event: {event}":
            return json.loads(lines[index + 1].removeprefix("data: "))
    raise AssertionError(f"no {event!r} event in:\n{body}")


def test_slow_provider_emits_heartbeat_frames_on_the_wire(monkeypatch, tmp_path) -> None:
    client = _app(
        monkeypatch,
        tmp_path,
        _SlowMock(delay=0.08),
        "heartbeat.db",
        TUTOR_STREAM_HEARTBEAT_SECONDS=0.02,
    )
    headers = _register_login(client, "hb@test.local")
    body = _stream(client, headers)
    kinds = _event_names(body)
    assert "heartbeat" in kinds, body
    payload = _data_after(body, "heartbeat")
    assert payload["interval_seconds"] == 0.02
    # heartbeats carry no answer content and the stream still completes.
    assert kinds[-1] == "done"


def test_grounded_answer_emits_citation_before_done(monkeypatch, tmp_path) -> None:
    client = _app(
        monkeypatch, tmp_path, MockLLMProvider(), "citation.db", TUTOR_STREAM_HEARTBEAT_SECONDS=0
    )
    headers = _register_login(client, "cite@test.local")
    body = _stream(client, headers)
    kinds = _event_names(body)
    assert "citation" in kinds, body
    assert kinds.index("citation") < kinds.index("done")
    citation = _data_after(body, "citation")
    assert citation["citation_verified"] is True
    assert citation["sources"], "the citation frame must carry the validated sources"
    done = _data_after(body, "done")
    assert [s["page"] for s in citation["sources"]] == [s["page"] for s in done["sources"]]


def test_mid_stream_failure_reaches_the_client_as_error_and_no_done(monkeypatch, tmp_path) -> None:
    client = _app(
        monkeypatch, tmp_path, _FailsMidStream(), "midfail.db", TUTOR_STREAM_HEARTBEAT_SECONDS=0
    )
    headers = _register_login(client, "mid@test.local")
    body = _stream(client, headers)
    kinds = _event_names(body)
    assert kinds[0] == "token", body
    assert "error" in kinds, body
    assert "done" not in kinds
    error = _data_after(body, "error")
    assert error["code"] == "llm_unavailable"
    # partial-answer persistence semantics: the user turn is stored, no
    # partial assistant row is written for a dropped stream.
    import sqlite3

    conn = sqlite3.connect(tmp_path / "midfail.db")
    rows = conn.execute("SELECT role FROM chat_messages ORDER BY id").fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["user"]


def test_open_circuit_without_fallback_degrades_with_an_honest_done(monkeypatch, tmp_path) -> None:
    # A circuit breaker only exists when a fallback provider is NAMED; naming
    # one whose key is absent (openai here) leaves the breaker wired with no
    # fallback behind it -- the exact topology in which the stream degrades to
    # the evidence-only answer instead of dying (handoff api-rag2.md, section 5).
    provider = _FailsMidStream()
    client = _app(
        monkeypatch,
        tmp_path,
        provider,
        "degrade.db",
        TUTOR_STREAM_HEARTBEAT_SECONDS=0,
        CIRCUIT_BREAKER_FAILURE_THRESHOLD=1,
        CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS=300,
        LLM_FALLBACK_PROVIDER="openai",
    )
    headers = _register_login(client, "degrade@test.local")
    # Trip the breaker with a first failing stream.
    first = _stream(client, headers)
    assert "error" in _event_names(first)
    # Next stream: circuit open, no fallback -> degraded evidence-only answer.
    conv = client.post("/tutor/conversations", json={}, headers=headers)
    res = client.post(
        f"/tutor/conversations/{conv.json()['id']}/messages/stream",
        json={"message": QUESTION},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.text
    kinds = _event_names(body)
    assert "error" in kinds and kinds[-1] == "done", body
    error = _data_after(body, "error")
    assert error.get("degraded") == "evidence_only"
    done = _data_after(body, "done")
    assert done["grounded"] is False
    assert done["sources"] == []
