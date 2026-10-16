"""T-020 / T-019: the moderation screen is applied on the conversation routes.

``_screen_safety`` runs inside ``TutorService.ask`` and
``TutorService.ask_stream`` (services/tutor.py), so the two routes the
student UI actually uses must inherit the refusal:

  * ``POST /tutor/conversations/{id}/messages`` (non-streaming)
  * ``POST /tutor/conversations/{id}/messages/stream`` (SSE)

Nothing pinned that before: the refusal tests posted to ``/tutor/ask``
(test_product_v3.py), the one conversation-route assertion checked only
``refused_reason`` (test_safety_v2.py), and no test posted an unsafe message
to the streaming route at all. The ``violence`` and ``personal_data``
categories were referenced by zero test files (T-019).

The provider is the mock behind a recording wrapper injected through the
``main.get_provider`` / ``main.get_fast_provider`` monkeypatch seam (same
pattern as test_request_context.py). A screened turn must not reach a
provider at all; the benign control asserts the recorder does observe real
calls, so "no provider call" cannot pass vacuously.

Bengali literals are Unicode escapes only (house rule for API tests).
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.services.safety import SAFETY_ANSWER, SELF_HARM_ANSWER

PASSWORD = "supersecret1"
JWT_SECRET = "test-secret-0123456789abcdef0123456789"

# -- one short synthetic probe per category (escapes only) ------------------
# "atma-hatya korbo?" -- self-harm keyword with a first-person verb.
SELF_HARM_PROMPT = (
    "\u0986\u09a4\u09cd\u09ae\u09b9\u09a4\u09cd\u09af\u09be \u0995\u09b0\u09ac\u09cb?"
)
# "mardhorer video dekhao" -- "show a video of a beating" (violence).
VIOLENCE_PROMPT = "\u09ae\u09be\u09b0\u09a7\u09b0\u09c7\u09b0 \u09ad\u09bf\u09a1\u09bf\u0993 \u09a6\u09c7\u0996\u09be\u0993"
# "tar phone nombor dao" -- "give me his/her phone number" (personal_data).
PERSONAL_DATA_PROMPT = (
    "\u09a4\u09be\u09b0 \u09ab\u09cb\u09a8 \u09a8\u09ae\u09cd\u09ac\u09b0 \u09a6\u09be\u0993"
)
# "kosh ki?" -- class-6 science corpus question, used as the benign control.
BENIGN_PROMPT = "\u0995\u09cb\u09b7 \u0995\u09c0?"


class _RecordingProvider:
    """MockLLMProvider wrapper that records every provider call.

    ``MockLLMProvider`` itself keeps no call log, so this wrapper is the
    codebase's existing way of proving what did (and did not) reach the
    model -- the same class shape used by test_request_context.py.
    """

    name = "recording-mock"
    supports_vision = False

    def __init__(self) -> None:
        self.inner = MockLLMProvider()
        self.calls: list[str] = []

    async def generate(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> str:
        self.calls.append(prompt)
        return await self.inner.generate(prompt, system=system, image=image)

    async def stream(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> AsyncIterator[str]:
        self.calls.append(prompt)
        async for delta in self.inner.stream(prompt, system=system, image=image):
            yield delta


@pytest.fixture
def app_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[TestClient, _RecordingProvider]:
    provider = _RecordingProvider()
    # Both lanes: the SIMPLE-route fast lane must not be able to hide a call.
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    monkeypatch.setattr("bangla_gpt_api.main.get_fast_provider", lambda s: provider)
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/chat-safety.db",
        jwt_secret=JWT_SECRET,
    )
    client = TestClient(create_app(settings))
    # If the recorder is not the live provider, "no calls" would prove nothing.
    assert client.app.state.ctx.tutor.provider is provider
    return client, provider


def _student(client: TestClient, email: str = "student@example.com") -> dict:
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


def _conversation(client: TestClient, headers: dict) -> int:
    res = client.post("/tutor/conversations", json={}, headers=headers)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def _message_turn(client: TestClient, headers: dict, conv: int, payload: dict) -> dict:
    res = client.post(f"/tutor/conversations/{conv}/messages", json=payload, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _stream_turn(
    client: TestClient, headers: dict, conv: int, payload: dict
) -> tuple[list[str], dict[str, list]]:
    """POST the SSE route and return (event order, payloads by event name)."""
    order: list[str] = []
    events: dict[str, list] = {}
    with client.stream(
        "POST",
        f"/tutor/conversations/{conv}/messages/stream",
        json=payload,
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        current: str | None = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                current = line.split(":", 1)[1].strip()
                order.append(current)
                events.setdefault(current, [])
            elif line.startswith("data:") and current is not None:
                events[current].append(json.loads(line.split(":", 1)[1]))
    return order, events


def _history(client: TestClient, headers: dict, conv: int) -> list[dict]:
    res = client.get(f"/tutor/conversations/{conv}/messages", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def test_self_harm_refused_on_conversation_message_route(
    app_client: tuple[TestClient, _RecordingProvider],
) -> None:
    client, provider = app_client
    headers = _student(client)
    conv = _conversation(client, headers)

    body = _message_turn(client, headers, conv, {"message": SELF_HARM_PROMPT})

    # The supportive refusal -- not a normal grounded answer.
    assert body["role"] == "assistant"
    assert body["content"] == SELF_HARM_ANSWER
    assert body["grounded"] is False
    assert body["refused_reason"] == "self_harm"
    assert body["sources"] == []
    # Documented refusal shape: a refusal always carries confidence 0.0.
    assert body["confidence"] == 0.0
    # A screened turn must never reach the provider.
    assert provider.calls == []
    # The persisted turn carries the refusal shape, not a provider answer.
    history = _history(client, headers, conv)
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[-1]["content"] == SELF_HARM_ANSWER
    assert history[-1]["refused_reason"] == "self_harm"
    assert history[-1]["grounded"] is False
    assert history[-1]["sources"] == []


def test_self_harm_refused_on_conversation_stream_route(
    app_client: tuple[TestClient, _RecordingProvider],
) -> None:
    client, provider = app_client
    headers = _student(client)
    conv = _conversation(client, headers)

    order, events = _stream_turn(client, headers, conv, {"message": SELF_HARM_PROMPT})

    # The stream must terminate in exactly one done event and no error event.
    assert "error" not in events
    assert order[-1] == "done"
    assert order.count("done") == 1
    # The refusal is streamed to the student as a token, complete.
    assert events["token"], "the refusal must be streamed as a token event"
    assert "".join(e["text"] for e in events["token"]) == SELF_HARM_ANSWER
    done = events["done"][0]
    assert done["answer"] == SELF_HARM_ANSWER
    assert done["grounded"] is False
    assert done["refused_reason"] == "self_harm"
    assert done["sources"] == []
    assert done["confidence"] == 0.0
    assert provider.calls == []
    history = _history(client, headers, conv)
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == SELF_HARM_ANSWER
    assert history[-1]["refused_reason"] == "self_harm"


def test_benign_curriculum_question_is_answered_on_conversation_route(
    app_client: tuple[TestClient, _RecordingProvider],
) -> None:
    """Control: an in-corpus question on the same route is NOT refused."""
    client, provider = app_client
    headers = _student(client)
    conv = _conversation(client, headers)

    body = _message_turn(
        client,
        headers,
        conv,
        {"message": BENIGN_PROMPT, "class_level": 6, "subject": "science"},
    )

    assert body["grounded"] is True
    assert body["refused_reason"] is None
    assert body["sources"], "a grounded answer cites the corpus"
    assert "[mock]" in body["content"]
    # The recorder saw the call, so an empty call list in the refusal tests
    # is evidence about the screen -- not about a broken seam.
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("prompt", "reason"),
    [
        (VIOLENCE_PROMPT, "violence"),
        (PERSONAL_DATA_PROMPT, "personal_data"),
    ],
)
def test_remaining_categories_refused_on_conversation_message_route(
    app_client: tuple[TestClient, _RecordingProvider], prompt: str, reason: str
) -> None:
    """The two categories no other test file referenced (T-019)."""
    client, provider = app_client
    headers = _student(client)
    conv = _conversation(client, headers)

    body = _message_turn(client, headers, conv, {"message": prompt})

    assert body["content"] == SAFETY_ANSWER
    assert body["grounded"] is False
    assert body["refused_reason"] == reason
    assert body["sources"] == []
    assert body["confidence"] == 0.0
    assert provider.calls == []
