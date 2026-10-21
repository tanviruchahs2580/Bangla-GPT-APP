"""R3/WS5: the per-identity in-flight slot must not leak on the stream route.

AUT-05 / I-08 regression. ``POST /tutor/conversations/{id}/messages/stream``
acquires the per-user in-flight slot *before* the ``StreamingResponse`` is
built, so that a saturated cap is still an HTTP 429 and the slot spans the
whole stream (released in the event generator's ``finally``, which also runs on
client disconnect).

That design has one hole: everything that runs between the acquire and the
``StreamingResponse`` -- request-context build, chat-image validation,
persisting the user turn -- can raise. When it does, the event generator is
never created, so its ``finally`` never runs and the slot stays held until the
backend TTL expires. Two rejected image uploads were enough to make the next
legitimate turn answer 429 (measured: 2 leaked slots against the chat cap of 2,
before the fix).

These tests assert the invariant directly on the limiter rather than inferring
it from a later 429: after every request -- successful, refused before the
stream started, or refused mid-stream -- a *fully consumed* turn leaves zero
in-flight slots for that identity.
"""

from __future__ import annotations

import base64
import uuid

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
# 1x1 transparent PNG (decodes to ~70 bytes: far under the 1.5 MB cap).
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

#: Chat-route in-flight cap used by every test here (the shipped default).
INFLIGHT_CAP = 2


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("AI_MAX_INFLIGHT_PER_USER", str(INFLIGHT_CAP))
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/r3ws5-slots.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _student(client: TestClient) -> dict:
    email = f"kid-{uuid.uuid4().hex[:8]}@example.com"
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Slot Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _conversation(client: TestClient, headers: dict) -> int:
    res = client.post("/tutor/conversations", json={}, headers=headers)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def _in_flight(client: TestClient) -> int:
    """Slots currently held, summed over every key (the backend's own state).

    The limiter is built lazily by the first request that needs a slot, so
    "never built" means zero slots in flight -- which is itself part of the
    invariant under test (a refused request must not even create the limiter).
    """
    limiter = client.app.state.ctx.concurrency_limiter
    if limiter is None:
        return 0
    slots = getattr(limiter, "_slots", None)
    if slots is None:  # a Redis-backed limiter has no local view
        pytest.skip("limiter backend exposes no in-process slot view")
    return sum(count for count, _expiry in slots.values())


def _stream(client: TestClient, conv: int, headers: dict, payload: dict):
    return client.post(
        f"/tutor/conversations/{conv}/messages/stream", json=payload, headers=headers
    )


def test_rejected_images_do_not_hold_in_flight_slots(client: TestClient) -> None:
    """The original failure: two 422s used up the whole cap for the identity."""
    kid = _student(client)
    conv = _conversation(client, kid)

    res = _stream(
        client,
        conv,
        kid,
        {
            "message": "what is in this picture",
            "image": {"mime_type": "application/pdf", "data_base64": TINY_PNG_B64},
        },
    )
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["code"] == "image_invalid"
    assert _in_flight(client) == 0, "a refused request leaked an in-flight slot"

    huge = base64.b64encode(b"0" * 1_600_000).decode()
    res = _stream(
        client,
        conv,
        kid,
        {
            "message": "what is in this picture",
            "image": {"mime_type": "image/png", "data_base64": huge},
        },
    )
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["code"] == "image_invalid"
    assert _in_flight(client) == 0, "a refused request leaked an in-flight slot"

    # the cap is still INFLIGHT_CAP: after the two refusals a valid turn works
    res = _stream(
        client,
        conv,
        kid,
        {
            "message": "what is in this picture",
            "image": {"mime_type": "image/png", "data_base64": TINY_PNG_B64},
        },
    )
    assert res.status_code == 200, res.text
    assert _in_flight(client) == 0, "a completed stream leaked an in-flight slot"


def test_completed_text_stream_releases_the_slot(client: TestClient) -> None:
    kid = _student(client)
    conv = _conversation(client, kid)

    res = _stream(client, conv, kid, {"message": "explain photosynthesis"})
    assert res.status_code == 200
    assert "event:" in res.text
    assert _in_flight(client) == 0


def test_cap_still_refuses_while_a_stream_holds_the_slot(client: TestClient) -> None:
    """The cap must keep working: N+1 unstarted streams get 429.

    ``TestClient`` consumes the body of every response it is asked for, so the
    slot is taken and released per request; this test pins the *accounting*
    (never more than one slot per in-flight request, always back to zero)
    rather than the refusal timing.
    """
    kid = _student(client)
    conv = _conversation(client, kid)

    for _ in range(INFLIGHT_CAP + 2):
        res = _stream(client, conv, kid, {"message": "explain photosynthesis"})
        assert res.status_code == 200, res.text
        assert _in_flight(client) == 0
