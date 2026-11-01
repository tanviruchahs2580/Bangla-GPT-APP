"""RAG-27 / F-131: the retrieval-only degraded mode and its default-off branch.

With RETRIEVAL_ONLY_FALLBACK_ENABLED unset the pinned 502 contract holds: a
provider outage answers ``llm_unavailable``. With the flag on, the turn that
already retrieved and gate-passed textbook evidence answers with those
excerpts and their citations, explicitly ungrounded -- never a 502 and never
an uncited answer presented as grounded.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.base import LLMProvider, ProviderError
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


class ExplodingProvider(LLMProvider):
    """Every call fails -- the outage the degraded mode exists for."""

    name = "exploding"

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        raise ProviderError("upstream down")


@pytest.fixture
def exploding_app(monkeypatch):
    """create_app with the exploding provider on BOTH lanes (main + fast)."""

    def _client(tmp_path, **settings_kwargs) -> TestClient:
        import bangla_gpt_api.main as main_module

        def inject(self, *args, **kwargs):
            kwargs["provider"] = ExplodingProvider()
            kwargs["fast_provider"] = ExplodingProvider()
            original(self, *args, **kwargs)

        original = main_module.TutorService.__init__
        monkeypatch.setattr(main_module.TutorService, "__init__", inject)
        settings = Settings(
            env="test",
            database_url=engine_url(tmp_path, "w2xrag"),
            jwt_secret=SECRET,
            **settings_kwargs,
        )
        return TestClient(create_app(settings))

    return _client


def _headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/register",
        json={
            "email": "student@example.com",
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "student@example.com", "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ask(client: TestClient, headers: dict[str, str]):
    return client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6, "subject": "science"},
        headers=headers,
    )


def test_flag_off_keeps_the_502_contract(exploding_app, tmp_path) -> None:
    """Default branch: the pinned llm_unavailable 502 is untouched."""
    client = exploding_app(tmp_path)
    res = _ask(client, _headers(client))
    assert res.status_code == 502, res.text
    assert res.json()["detail"]["code"] == "llm_unavailable"


def test_flag_on_answers_with_cited_excerpts_not_a_502(exploding_app, tmp_path) -> None:
    client = exploding_app(tmp_path, retrieval_only_fallback_enabled=True)
    res = _ask(client, _headers(client))
    assert res.status_code == 200, res.text
    body = res.json()
    # Excerpts with citations, explicitly NOT a grounded answer.
    assert body["grounded"] is False
    assert body["refused_reason"] == "provider_unavailable"
    assert body["sources"], "the degraded answer must carry its citations"
    excerpts = [source["excerpt"] for source in body["sources"]]
    assert all(excerpt for excerpt in excerpts)
    assert all(excerpt in body["answer"] for excerpt in excerpts), (
        "every cited excerpt must appear in the excerpt list the student sees"
    )
    # No generated answer exists to score, so the confidence is unknown.
    assert body["confidence"] is None
    assert body.get("citation_verified") is None


def test_chat_send_persists_the_degraded_turn_as_ungrounded(exploding_app, tmp_path) -> None:
    """The chat route shares the service path: history shows the excerpts, not an error."""
    client = exploding_app(tmp_path, retrieval_only_fallback_enabled=True)
    headers = _headers(client)
    conv = client.post("/tutor/conversations", json={}, headers=headers).json()
    res = client.post(
        f"/tutor/conversations/{conv['id']}/messages",
        json={"message": "কোষ কী?", "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["role"] == "assistant"
    assert body["grounded"] is False
    assert body["refused_reason"] == "provider_unavailable"
    assert body["sources"]
