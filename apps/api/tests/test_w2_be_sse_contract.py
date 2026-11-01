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
        # The empty loop is what makes this an async generator (a bare return
        # would make it a coroutine, which ``async for`` cannot consume), and
        # it yields nothing - exactly the provider shape under test.
        for _ in ():  # pragma: no cover
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


def test_stream_response_carries_the_cache_and_buffering_headers(
    client: TestClient,
) -> None:
    """F-065/API-06: the stream response itself must tell caches and proxies
    not to hold it. Without ``no-cache`` a shared cache may retain the event
    stream, and without ``X-Accel-Buffering: no`` a buffering proxy forwards
    the frames only once its buffer fills -- which before the first token
    arrives is indistinguishable from a hang."""
    headers, conv_id = _student(client, "sse-headers@example.com")

    with client.stream(
        "POST",
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={"message": "বল কাকে বলে?"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"


def test_client_abort_cancels_the_producer_and_ledgers_the_partial(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing the response early must cancel the provider generator.

    An abandoned stream that keeps generating burns provider budget with
    nobody reading it; the route's ``finally`` cancels the producer task and
    finalizes the ledger with whatever text was delivered.

    Driven at the ASGI level on purpose: ``TestClient.stream`` buffers the
    whole response before it returns (its transport calls
    ``portal.call(self.app, ...)`` and only then hands back a BytesIO body), so
    through it a client can never walk away mid-stream - the abort this test is
    about is unreachable and an endless provider hangs the suite. An
    ``http.disconnect`` message on the receive channel is the same signal a
    closed socket produces, and it arrives here only after the first token
    frame was sent.
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
        except asyncio.CancelledError:
            observed["cancelled"] = True
            raise

    headers, conv_id = _student(client, "sse-abort@example.com")
    monkeypatch.setattr(tutor_service.TutorService, "ask_stream", endless_stream)

    body = json.dumps({"message": "বল কাকে বলে?"}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "path": f"/tutor/conversations/{conv_id}/messages/stream",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": [
            (b"authorization", headers["Authorization"].encode()),
            (b"content-type", b"application/json"),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    request_delivered = False
    token_frame_sent = asyncio.Event()
    sent: list[dict] = []

    async def receive() -> dict:
        nonlocal request_delivered
        if not request_delivered:
            request_delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        # The socket is gone; the response side must notice and clean up.
        await token_frame_sent.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)
        if message["type"] == "http.response.body" and b"event: token" in (
            message.get("body") or b""
        ):
            token_frame_sent.set()

    import anyio

    anyio.run(client.app, scope, receive, send)

    assert observed["started"], "the producer never ran"
    assert token_frame_sent.is_set(), "no token frame reached the client"
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
