"""W2/API-06 (F-065): the SSE wire contract, exercised with a streaming client.

The contract: ``text/event-stream`` responses carry ``token`` events (one JSON
object per delta), one final ``done`` event whose data is the full answer plus
the persisted message ids, ``: ping`` comment lines while nothing is arriving
(covered in test_sse_heartbeat.py), and exactly one ``error`` event instead of
``done`` when the provider fails or produces nothing. A client that walks away
mid-stream must cancel the provider work rather than leave it running.

The event names and payload keys here are the contract the web client parses;
a rename without this file changing is the defect this test exists to catch.
"""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

import bangla_gpt_api.services.tutor as tutor_service
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.services.tutor import AskResponse, StreamEvent
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "sse_contract"),
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _student(client: TestClient, email: str = "sse@example.com") -> tuple[dict, int]:
    assert (
        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "name": "শিক্ষার্থী",
                "role": "student",
                "guardian_consent": True,
                "class_level": 6,
            },
        ).status_code
        == 201
    )
    token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()[
        "access_token"
    ]
    headers = {"Authorization": f"Bearer {token}"}
    conv = client.post("/tutor/conversations", json={}, headers=headers).json()
    return headers, conv["id"]


def _events(lines) -> list[tuple[str, dict | None]]:
    """Parse an SSE byte stream into (event, data) pairs; comments are skipped."""
    out: list[tuple[str, dict | None]] = []
    event = ""
    for line in lines:
        if line.startswith("event: "):
            event = line.split(": ", 1)[1]
        elif line.startswith("data: "):
            out.append((event, json.loads(line.split(": ", 1)[1])))
    return out


def test_provider_failure_answers_one_error_event_and_no_done(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider that dies mid-stream: the deltas already sent stay valid,
    then exactly one error event closes the turn (never a done event with
    fabricated content)."""
    headers, conv_id = _student(client)

    async def dying_stream(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        yield StreamEvent(type="token", text="প্রথম অংশ")
        raise ProviderError("provider dropped the connection")

    monkeypatch.setattr(tutor_service.TutorService, "ask_stream", dying_stream)

    with client.stream(
        "POST",
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={"message": "বল কাকে বলে?"},
        headers=headers,
    ) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response.iter_lines())

    kinds = [kind for kind, _data in events]
    assert kinds.count("error") == 1, events
    assert "done" not in kinds, events
    assert ("token", {"text": "প্রথম অংশ"}) in events
    error_data = next(data for kind, data in events if kind == "error")
    assert error_data["code"] == "llm_unavailable"

    # The user turn survives; no assistant turn was persisted.
    history = client.get(f"/tutor/conversations/{conv_id}/messages", headers=headers).json()
    assert [m["role"] for m in history] == ["user"]


def test_producer_that_yields_nothing_answers_the_coded_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The no-response guard: a provider that returns without a final event
    must produce the coded error, never a naked 500 or an empty stream."""

    async def empty_stream(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if False:  # pragma: no cover - marks this an async generator
            yield StreamEvent(type="token", text="")

    headers, conv_id = _student(client, "sse-empty@example.com")
    monkeypatch.setattr(tutor_service.TutorService, "ask_stream", empty_stream)

    with client.stream(
        "POST",
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={"message": "বল কাকে বলে?"},
        headers=headers,
    ) as response:
        events = _events(response.iter_lines())

    assert [kind for kind, _d in events] == ["error"]
    assert events[0][1]["code"] == "llm_unavailable"


def test_client_abort_cancels_the_producer_and_ledgers_the_partial(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing the response early must cancel the provider generator.

    An abandoned stream that keeps generating burns provider budget with
    nobody reading it; the route's ``finally`` cancels the producer task and
    finalizes the ledger with whatever text was delivered.
    """
    observed: dict[str, bool] = {"started": False, "cancelled": False}

    async def endless_stream(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        observed["started"] = True
        try:
            yield StreamEvent(type="token", text="শুরু")
            # Keep the producer alive until the route cancels it on the client
            # abort. An Event never set is the idiomatic wait (ruff ASYNC110):
            # a busy `while True: sleep` also holds the loop awake under load.
            await asyncio.Event().wait()
        finally:
            observed["cancelled"] = True

    headers, conv_id = _student(client, "sse-abort@example.com")
    monkeypatch.setattr(tutor_service.TutorService, "ask_stream", endless_stream)

    with client.stream(
        "POST",
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={"message": "বল কাকে বলে?"},
        headers=headers,
    ) as response:
        saw_token = False
        for line in response.iter_lines():
            if line.startswith("event: token"):
                saw_token = True
                break  # walk away mid-stream
        assert saw_token

    # Deterministic wait: poll for the cancellation instead of sleeping a
    # fixed amount; the margin only bounds a failure, it is not a delay.
    deadline = time.monotonic() + 10.0
    while not observed["cancelled"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert observed["started"], "the producer never ran"
    assert observed["cancelled"], "the producer task was not cancelled on abort"


def test_done_event_carries_the_contract_fields(client: TestClient) -> None:
    """The final event's keys are the client contract: message ids, the full
    answer and the grounding flag (plus additive confidence)."""
    headers, conv_id = _student(client, "sse-done@example.com")

    with client.stream(
        "POST",
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={"message": "বল কাকে বলে?"},
        headers=headers,
    ) as response:
        events = _events(response.iter_lines())

    done = [data for kind, data in events if kind == "done"]
    assert len(done) == 1, events
    payload = done[0]
    assert set(payload) >= {
        "user_message_id",
        "message_id",
        "answer",
        "grounded",
        "sources",
        "refused_reason",
        "confidence",
    }
    assert isinstance(payload["answer"], str) and payload["answer"]
    assert 0.0 <= float(payload["confidence"]) <= 1.0
    assert isinstance(payload["sources"], list)
    # AskResponse fields survive the round trip (no renames on the wire).
    assert set(payload) >= set(AskResponse.model_fields)
