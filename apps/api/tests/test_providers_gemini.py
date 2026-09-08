import json

import httpx
import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.providers import ProviderNotConfigured, get_provider
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.providers.gemini import GeminiProvider

MODEL = "gemini-2.5-flash"


def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"parts": [{"text": text}], "role": "model"},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"totalTokenCount": 10},
        },
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta"),
    )


def _error_response(status: int, message: str, status_name: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"code": status, "message": message, "status": status_name}},
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta"),
    )


async def test_generate_success_contract() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok_response("à¦‰à¦¤à§à¦¤à¦°")

    provider = GeminiProvider(
        api_key="test-key",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    answer = await provider.generate("à¦ªà§à¦°à¦¶à§à¦¨?", system="à¦¨à¦¿à¦¯à¦¼à¦®")
    assert answer == "à¦‰à¦¤à§à¦¤à¦°"

    request = seen[0]
    assert f"/v1beta/models/{MODEL}:generateContent" in str(request.url)
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content.decode())
    assert body["contents"][0]["role"] == "user"
    assert body["contents"][0]["parts"][0]["text"] == "à¦ªà§à¦°à¦¶à§à¦¨?"
    assert body["systemInstruction"]["parts"][0]["text"] == "à¦¨à¦¿à¦¯à¦¼à¦®"


async def test_retryable_status_then_success() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _error_response(429, "quota exceeded", "RESOURCE_EXHAUSTED")
        return _ok_response("à¦¸à¦«à¦²")

    provider = GeminiProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )
    assert await provider.generate("q") == "à¦¸à¦«à¦²"
    assert len(calls) == 2


async def test_retries_exhausted_raise_provider_error() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _error_response(503, "backend error", "UNAVAILABLE")

    provider = GeminiProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="Gemini API error 503"):
        await provider.generate("q")
    assert len(calls) == 3  # initial attempt + max_retries


async def test_non_retryable_client_error_does_not_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _error_response(401, "API key not valid", "PERMISSION_DENIED")

    provider = GeminiProvider(
        api_key="bad",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=3,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="401"):
        await provider.generate("q")
    assert len(calls) == 1


async def test_stream_error_after_retries_raises_provider_error() -> None:
    # Regression: the stream error path passed a parsed dict into the
    # Response-shaped _error_message helper, crashing with AttributeError
    # instead of ProviderError -- which escaped the SSE handler's
    # `except ProviderError` and killed the connection mid-stream.
    def handler(request: httpx.Request) -> httpx.Response:
        return _error_response(429, "Resource has been exhausted", "RESOURCE_EXHAUSTED")

    provider = GeminiProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="Gemini API error 429"):
        async for _ in provider.stream("q"):
            pass


async def test_blocked_candidate_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"finishReason": "SAFETY"}]},
            request=httpx.Request("POST", "https://example.invalid"),
        )

    provider = GeminiProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="no text|no candidates"):
        await provider.generate("q")


async def test_timeout_maps_to_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    provider = GeminiProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=0.01,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="timed out"):
        await provider.generate("q")


def test_factory_requires_api_key() -> None:
    settings = Settings(env="test", llm_provider="gemini", gemini_api_key=None)
    with pytest.raises(ProviderNotConfigured):
        get_provider(settings)


def test_factory_builds_gemini_when_configured() -> None:
    settings = Settings(env="test", llm_provider="gemini", gemini_api_key="secret")
    provider = get_provider(settings)
    assert provider.name == "gemini"


def test_factory_rejects_unknown_provider() -> None:
    settings = Settings(env="test", llm_provider="openai")
    with pytest.raises(ProviderNotConfigured):
        get_provider(settings)
