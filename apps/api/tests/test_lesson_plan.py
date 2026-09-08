"""S2.6: lesson plan copilot -- one AI call fills all eight sections.

Chapter title 'kosh' (cell) from the sample NCTB class-6 science corpus;
built from codepoints so transport/tooling never mutates the Bengali.
"""

import json

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.services.generators.lesson_plan import (
    LESSON_KEYS,
    parse_lesson_payload,
)

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)


class _FakeProvider:
    name = "fake"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0
        self.prompts: list[str] = []

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        return self.reply

    async def stream(self, prompt: str, *, system: str | None = None):
        yield self.reply


def _valid_payload() -> dict[str, str]:
    return {key: f"{key}-text" for key in LESSON_KEYS}


def _make_client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/lesson.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _patched_client(tmp_path, monkeypatch, provider: _FakeProvider) -> TestClient:
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    return _make_client(tmp_path)


def _teacher_headers(client: TestClient) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={
            "email": "teach@example.com",
            "password": PASSWORD,
            "name": "Teacher",
            "role": "teacher",
        },
    )
    res = client.post(
        "/auth/login",
        json={"email": "teach@example.com", "password": PASSWORD},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _plan(client: TestClient, headers: dict, **over):
    body = {"class_level": 6, "subject": "science", "chapter": CHAPTER, "minutes": 35}
    body.update(over)
    return client.post("/teacher/lesson-plans", json=body, headers=headers)


@pytest.fixture
def client(tmp_path) -> TestClient:
    return _make_client(tmp_path)


def test_single_ai_call_produces_eight_sections(tmp_path, monkeypatch) -> None:
    provider = _FakeProvider(json.dumps(_valid_payload()))
    client = _patched_client(tmp_path, monkeypatch, provider)
    headers = _teacher_headers(client)
    res = _plan(client, headers, level="advanced")
    assert res.status_code == 200, res.text
    body = res.json()
    assert provider.calls == 1, "exactly one AI call must produce all sections"
    prompt = provider.prompts[0]
    assert "LESSON_JSON_V1" in prompt
    assert "<evidence>" in prompt, "prompt must carry the RAG context"
    assert "minutes=35, level=advanced" in prompt
    # Sections arrive in the exact eight-step teaching order from the spec.
    assert list(body["sections"].keys()) == list(LESSON_KEYS)
    assert all(v.strip() for v in body["sections"].values())
    assert body["sources"], "plan must cite retrieved textbook chunks"
    assert body["minutes"] == 35 and body["level"] == "advanced"


def test_invalid_provider_output_is_502(tmp_path, monkeypatch) -> None:
    provider = _FakeProvider("the provider rambled without any json")
    client = _patched_client(tmp_path, monkeypatch, provider)
    headers = _teacher_headers(client)
    assert _plan(client, headers).status_code == 502


def test_unknown_chapter_is_502_without_ai_call(tmp_path, monkeypatch) -> None:
    provider = _FakeProvider(json.dumps(_valid_payload()))
    client = _patched_client(tmp_path, monkeypatch, provider)
    headers = _teacher_headers(client)
    res = _plan(client, headers, chapter="xyzzy-not-in-corpus")
    assert res.status_code == 502
    assert provider.calls == 0, "no evidence -> no AI call"


def test_roles_gated(client: TestClient) -> None:
    assert client.post("/teacher/lesson-plans", json={}).status_code == 401
    client.post(
        "/auth/register",
        json={
            "email": "kid@example.com",
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    res = client.post(
        "/auth/login",
        json={"email": "kid@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    assert _plan(client, headers).status_code == 403


def test_mock_provider_satisfies_lesson_contract(client: TestClient) -> None:
    """Live default-mock path: eight non-empty sections in spec order."""
    headers = _teacher_headers(client)
    res = _plan(client, headers)
    assert res.status_code == 200, res.text
    sections = res.json()["sections"]
    assert list(sections.keys()) == list(LESSON_KEYS)
    assert all(v.strip() for v in sections.values())


def test_parse_accepts_fenced_json_and_rejects_short_payloads() -> None:
    fenced = "```json\n" + json.dumps(_valid_payload()) + "\n```"
    assert parse_lesson_payload(fenced) == _valid_payload()
    with pytest.raises(ProviderError):
        short = {k: v for k, v in _valid_payload().items() if k != "homework"}
        parse_lesson_payload(json.dumps(short))
    with pytest.raises(ProviderError):
        parse_lesson_payload(json.dumps({**_valid_payload(), "questions": "   "}))
    with pytest.raises(ProviderError):
        parse_lesson_payload("no json here")
