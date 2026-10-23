"""F-141: a silent SSE connection must not look dead to proxies.

Retrieval plus provider time-to-first-token can legitimately exceed proxy
and load-balancer idle timeouts (commonly 30-60s). The stream therefore
emits a ``: ping`` comment line every ``SSE_HEARTBEAT_SECONDS`` of
silence. A comment carries no data: browsers ignore it by spec, and this
app's own parser only reads ``event:``/``data:`` lines, so the extra
bytes change nothing for clients — the connection just stays observably
alive instead of being cut before the first token.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import bangla_gpt_api.routers.tutor as routers_tutor
import bangla_gpt_api.services.tutor as tutor_service
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/heartbeat.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str) -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_stream_emits_ping_comments_while_first_token_is_delayed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first token slower than the heartbeat window must produce ``: ping``
    comment lines, and the token/done events must still arrive intact."""
    _register(client, "slow@example.com")
    headers = _login(client, "slow@example.com")
    conv = client.post("/tutor/conversations", json={}, headers=headers).json()

    # shrink the heartbeat window to test-speed
    monkeypatch.setattr(routers_tutor, "SSE_HEARTBEAT_SECONDS", 0.05)

    real_ask_stream = tutor_service.TutorService.ask_stream

    async def slow_first_token(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.2)  # 4x the patched heartbeat window
        async for event in real_ask_stream(self, *args, **kwargs):
            yield event

    monkeypatch.setattr(tutor_service.TutorService, "ask_stream", slow_first_token)

    with client.stream(
        "POST",
        f"/tutor/conversations/{conv['id']}/messages/stream",
        json={"message": "বল কাকে বলে?"},
        headers=headers,
    ) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        pings = 0
        tokens = 0
        saw_done = False
        for line in response.iter_lines():
            if line.strip() == ": ping":
                pings += 1
            elif line.startswith("event: token"):
                tokens += 1
            elif line.startswith("event: done"):
                saw_done = True
    assert pings >= 2, "expected keepalive comments during the silent window"
    assert tokens >= 1, "token events must still arrive after the delay"
    assert saw_done, "the turn must still complete with one done event"

    history = client.get(f"/tutor/conversations/{conv['id']}/messages", headers=headers).json()
    assert [m["role"] for m in history] == ["user", "assistant"]


def test_fast_stream_emits_no_ping_comments(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mock provider answers instantly; an instant stream must not gain
    keepalive noise (comments exist only to cover silence)."""
    _register(client, "fast@example.com")
    headers = _login(client, "fast@example.com")
    conv = client.post("/tutor/conversations", json={}, headers=headers).json()

    monkeypatch.setattr(routers_tutor, "SSE_HEARTBEAT_SECONDS", 60.0)

    with client.stream(
        "POST",
        f"/tutor/conversations/{conv['id']}/messages/stream",
        json={"message": "বল কাকে বলে?"},
        headers=headers,
    ) as response:
        lines = list(response.iter_lines())

    assert not any(line.strip() == ": ping" for line in lines)
    assert any(line.startswith("event: token") for line in lines)
    done_rows = [
        json.loads(line.split(":", 1)[1])
        for line in lines
        if line.startswith("data:") and "user_message_id" in line
    ]
    assert len(done_rows) == 1
    assert done_rows[0]["answer"], "final event carries the full answer"
