"""S2.3: content engine -- one AI call fills all seven sections; edits version up."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.mock import MockLLMProvider

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"

# Chapter title 'kosh' from the sample NCTB class-6 science corpus.
CHAPTER = "কোষ"

SECTION_KEYS = [
    "summary",
    "notes",
    "key_points",
    "examples",
    "practice_qs",
    "homework",
    "exam_tips",
]


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


def _valid_payload() -> dict:
    return {
        "summary": "summary-text",
        "notes": "notes-text",
        "key_points": ["kp-1", "kp-2"],
        "examples": ["ex-1"],
        "practice_qs": ["pq-1", "pq-2"],
        "homework": ["hw-1"],
        "exam_tips": ["tip-1"],
    }


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/content.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


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


def _generate(client: TestClient, headers: dict, chapter: str = CHAPTER):
    return client.post(
        "/teacher/content/generate",
        json={"class_level": 6, "subject": "science", "chapter": chapter},
        headers=headers,
    )


def test_generate_single_ai_call_all_sections(monkeypatch, tmp_path) -> None:
    provider = _FakeProvider(json.dumps(_valid_payload()))
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/content.db",
        jwt_secret=SECRET,
    )
    client = TestClient(create_app(settings))
    headers = _teacher_headers(client)
    res = _generate(client, headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert provider.calls == 1, "exactly one AI call must produce all sections"
    assert "CONTENT_JSON_V1" in provider.prompts[0]
    assert "<evidence>" in provider.prompts[0], "prompt must carry the RAG context"
    assert body["version"] == 1 and body["source"] == "ai"
    assert sorted(body["sections"].keys()) == sorted(SECTION_KEYS)
    assert body["sections"]["practice_qs"] == ["pq-1", "pq-2"]
    assert body["sources"], "generation must cite retrieved textbook chunks"


def test_teacher_edit_persists_as_new_version(monkeypatch, tmp_path) -> None:
    provider = _FakeProvider(json.dumps(_valid_payload()))
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/content.db",
        jwt_secret=SECRET,
    )
    client = TestClient(create_app(settings))
    headers = _teacher_headers(client)
    assert _generate(client, headers).status_code == 200

    edited = _valid_payload()
    edited["summary"] = "teacher-summary"
    res = client.put(
        "/teacher/content",
        json={
            "class_level": 6,
            "subject": "science",
            "chapter": CHAPTER,
            "sections": edited,
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["version"] == 2 and res.json()["source"] == "teacher"
    assert provider.calls == 1, "editing must not trigger another AI call"

    cur = client.get(
        "/teacher/content",
        params={"class_level": 6, "subject": "science", "chapter": CHAPTER},
        headers=headers,
    ).json()
    assert cur["sections"]["summary"] == "teacher-summary"

    hist = client.get(
        "/teacher/content/history",
        params={"class_level": 6, "subject": "science", "chapter": CHAPTER},
        headers=headers,
    ).json()
    assert [h["version"] for h in hist] == [2, 1]
    assert [h["source"] for h in hist] == ["teacher", "ai"]


def test_invalid_provider_output_is_502_and_persists_nothing(monkeypatch, tmp_path) -> None:
    provider = _FakeProvider("the provider rambled without any json")
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/content.db",
        jwt_secret=SECRET,
    )
    client = TestClient(create_app(settings))
    headers = _teacher_headers(client)
    res = _generate(client, headers)
    assert res.status_code == 502
    missing = client.get(
        "/teacher/content",
        params={"class_level": 6, "subject": "science", "chapter": CHAPTER},
        headers=headers,
    )
    assert missing.status_code == 404


def test_unknown_chapter_is_502_without_ai_call(monkeypatch, tmp_path) -> None:
    provider = _FakeProvider(json.dumps(_valid_payload()))
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/content.db",
        jwt_secret=SECRET,
    )
    client = TestClient(create_app(settings))
    headers = _teacher_headers(client)
    res = _generate(client, headers, chapter="xyzzy-not-in-corpus")
    assert res.status_code == 502
    assert provider.calls == 0, "no evidence -> no AI call"


def test_mock_provider_satisfies_content_contract(client: TestClient) -> None:
    """Live-path check with the default mock provider: all seven sections."""
    headers = _teacher_headers(client)
    res = _generate(client, headers)
    assert res.status_code == 200, res.text
    sections = res.json()["sections"]
    assert sorted(sections.keys()) == sorted(SECTION_KEYS)
    assert sections["summary"].strip()
    assert len(sections["key_points"]) >= 1


def test_mock_provider_unit_contract() -> None:
    from bangla_gpt_api.services.generators.chapter_content import (
        CONTENT_JSON_MARKER,
        parse_content_payload,
    )

    prompt = f"{CONTENT_JSON_MARKER} ... <evidence>পাঠ্য অংশ। দ্বিতীয় বাক্য।</evidence>"
    raw = asyncio.run(MockLLMProvider().generate(prompt))
    payload = parse_content_payload(raw)
    assert sorted(payload.keys()) == sorted(SECTION_KEYS)


def test_content_endpoints_require_teacher(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={
            "email": "stud@example.com",
            "password": PASSWORD,
            "name": "Student",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    res = client.post(
        "/auth/login",
        json={"email": "stud@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    assert _generate(client, headers).status_code == 403
    denied = client.get(
        "/teacher/content",
        params={"class_level": 6, "subject": "science", "chapter": CHAPTER},
        headers=headers,
    )
    assert denied.status_code == 403
