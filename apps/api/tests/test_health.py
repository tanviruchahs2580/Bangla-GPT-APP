import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers import ProviderNotConfigured, get_provider


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(env="test")))


def test_health_reports_app_identity(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    # F-SEC-07: health is now minimal {"status":"ok"}; version/env moved to /admin/system/info
    assert body["status"] == "ok"
    assert "version" not in body or body.get("version") is None
    # authenticated detail endpoint still carries version
    from fastapi.testclient import TestClient as _TC

    from bangla_gpt_api.main import create_app as _ca

    c2 = _TC(
        _ca(
            Settings(
                env="test",
                database_url="sqlite:///:memory:",
                jwt_secret="test-secret-0123456789abcdef0123456789",
                admin_email="adm@test.com",
                admin_password="supersecret1",
                force_admin_password_change=False,
            )
        )
    )
    adm_tok = c2.post(
        "/auth/login",
        json={"email": "adm@test.com", "password": "supersecret1"},
    ).json()["access_token"]
    r2 = c2.get("/admin/system/info", headers={"Authorization": f"Bearer {adm_tok}"})
    assert r2.status_code == 200
    assert r2.json()["version"] == Settings(env="test").version


def test_live_endpoint(client: TestClient) -> None:
    res = client.get("/live")
    assert res.status_code == 200
    assert res.json() == {"status": "alive"}


def test_ready_with_mock_provider(client: TestClient) -> None:
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready", "provider": "mock"}


def test_ready_returns_503_for_unconfigured_provider() -> None:
    client = TestClient(create_app(Settings(llm_provider="does-not-exist")))
    res = client.get("/ready")
    assert res.status_code == 503
    assert "does-not-exist" in res.json()["detail"]


@pytest.mark.asyncio
async def test_mock_provider_is_deterministic() -> None:
    settings = Settings(llm_provider="mock")
    provider = get_provider(settings)
    first = await provider.generate("১ + ১ কত?")
    second = await provider.generate("১ + ১ কত?")
    assert first == second
    assert "[mock]" in first


def test_unknown_provider_raises_clear_error() -> None:
    settings = Settings(llm_provider="nope")
    with pytest.raises(ProviderNotConfigured, match="nope"):
        get_provider(settings)


def test_mock_provider_with_system_prompt() -> None:
    import asyncio

    from bangla_gpt_api.providers.mock import MockLLMProvider

    provider = MockLLMProvider()
    out = asyncio.run(provider.generate("hello", system="tutor"))
    # AUD-01: the internal system prompt must never leak into the answer.
    assert "tutor" not in out
    assert out == "[mock] hello"


def test_mock_provider_quotes_evidence_without_markup() -> None:
    import asyncio

    from bangla_gpt_api.providers.mock import MockLLMProvider

    provider = MockLLMProvider()
    prompt = (
        "নির্দেশনা <evidence> কোষ হলো ক্ষুদ্রতম একক। </evidence> "
        "<evidence> কোষের তিনটি অংশ। </evidence> প্রশ্ন: <user_question>কোষ কী?</user_question>"
    )
    out = asyncio.run(provider.generate(prompt, system="SYSTEM-PROMPT-TEXT"))
    assert "SYSTEM-PROMPT-TEXT" not in out
    assert "<evidence>" not in out and "<user_question>" not in out
    # S1.4: the mock returns the evidence in sectioned layout; sentences are split
    # on the danda, so assert the clause text itself is quoted.
    assert "কোষ হলো ক্ষুদ্রতম একক" in out
    assert "সহজ ব্যাখ্যা:" in out and "মূল বিষয়:" in out
