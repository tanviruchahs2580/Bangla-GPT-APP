"""Tests for the OpenAI-compatible provider.

Contract verified against the OpenAI Chat Completions API documentation
(platform.openai.com/docs/api-reference/chat):

- POST https://api.openai.com/v1/chat/completions
- authentication via Authorization: Bearer <key>
- response text in choices[0].message.content
- streaming via stream=true with SSE data: ... lines
"""

import json

import httpx
import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.providers import (
    ProviderNotConfigured,
    get_fallback_provider,
    get_fast_provider,
    get_provider,
)
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.providers.openai import OpenAIProvider

MODEL = "gpt-4o-mini"


def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )


def _error_response(status: int, message: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"code": status, "message": message, "type": "invalid_request_error"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )


# ── generate() ──────────────────────────────────────────────────────────────


async def test_generate_success_contract() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok_response("উত্তর")

    provider = OpenAIProvider(
        api_key="test-key",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    answer = await provider.generate("প্রশ্ন?", system="সিস্টেম")
    assert answer == "উত্তর"

    request = seen[0]
    assert "/v1/chat/completions" in str(request.url)
    assert request.headers["authorization"].startswith("Bearer ")
    assert request.headers["content-type"] == "application/json"
    body = json.loads(request.content.decode())
    assert body["model"] == MODEL
    assert body["messages"][0] == {"role": "system", "content": "সিস্টেম"}
    assert body["messages"][1] == {"role": "user", "content": "প্রশ্ন?"}


async def test_generate_no_system() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok_response("hello")

    provider = OpenAIProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    await provider.generate("hi")
    body = json.loads(seen[0].content.decode())
    assert len(body["messages"]) == 1
    assert body["messages"][0] == {"role": "user", "content": "hi"}


async def test_retryable_status_then_success() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _error_response(429, "rate limited")
        return _ok_response("ok")

    provider = OpenAIProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )
    assert await provider.generate("q") == "ok"
    assert len(calls) == 2


async def test_retries_exhausted_raises_provider_error() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _error_response(503, "service unavailable")

    provider = OpenAIProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="OpenAI API error 503"):
        await provider.generate("q")
    assert len(calls) == 3  # initial + max_retries


async def test_non_retryable_400_does_not_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _error_response(400, "bad model")

    provider = OpenAIProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=3,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="400"):
        await provider.generate("q")
    assert len(calls) == 1


async def test_blocked_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": None}}]},
            request=httpx.Request("POST", "https://example.invalid"),
        )

    provider = OpenAIProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="no text"):
        await provider.generate("q")


async def test_timeout_maps_to_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    provider = OpenAIProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=0.01,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="timed out"):
        await provider.generate("q")


# ── stream() ────────────────────────────────────────────────────────────────


async def test_stream_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Standard SSE format: each data line ends with double newline
        body1 = json.dumps({"choices": [{"delta": {"content": "ন"}}]})
        body2 = json.dumps({"choices": [{"delta": {"content": "উ"}}]})
        raw = f"data: {body1}\n\ndata: {body2}\n\ndata: [DONE]\n\n"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=raw.encode(),
            request=request,
        )

    provider = OpenAIProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    chunks = []
    async for delta in provider.stream("q"):
        chunks.append(delta)
    assert "".join(chunks) == "নউ"


async def test_stream_error_after_retries_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _error_response(429, "rate limited")

    provider = OpenAIProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="OpenAI API error 429"):
        async for _ in provider.stream("q"):
            pass


async def test_stream_no_text_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Server returns 200 but no text deltas
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n",
            request=request,
        )

    provider = OpenAIProvider(
        api_key="k",
        model=MODEL,
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="no text"):
        async for _ in provider.stream("q"):
            pass


# ── factory ─────────────────────────────────────────────────────────────────


async def test_factory_requires_api_key() -> None:
    settings = Settings(env="test", llm_provider="openai", openai_api_key=None)
    with pytest.raises(ProviderNotConfigured):
        get_provider(settings)


async def test_factory_builds_openai_when_configured() -> None:
    settings = Settings(env="test", llm_provider="openai", openai_api_key="sk-secret")
    provider = get_provider(settings)
    assert provider.name == "openai"


async def test_factory_rejects_unknown_provider() -> None:
    settings = Settings(env="test", llm_provider="anthropic")
    with pytest.raises(ProviderNotConfigured):
        get_provider(settings)


# ── get_fast_provider ───────────────────────────────────────────────────────


async def test_fast_provider_gemini_requires_model() -> None:
    settings = Settings(env="test", llm_provider="gemini", gemini_api_key="k")
    with pytest.raises(ProviderNotConfigured):
        get_fast_provider(settings)


async def test_fast_provider_gemini_with_model() -> None:
    settings = Settings(
        env="test", llm_provider="gemini", gemini_api_key="k", gemini_fast_model="gemini-2.5-flash"
    )
    fast = get_fast_provider(settings)
    assert fast.name == "gemini"


async def test_fast_provider_mock_works_without_config() -> None:
    settings = Settings(env="test", llm_provider="mock")
    fast = get_fast_provider(settings)
    assert fast.name == "mock"


async def test_fast_provider_openai_uses_main_model() -> None:
    settings = Settings(env="test", llm_provider="openai", openai_api_key="sk-x")
    fast = get_fast_provider(settings)
    assert fast.name == "openai"


# ── get_fallback_provider ───────────────────────────────────────────────────


async def test_fallback_gemini_to_openai() -> None:
    settings = Settings(
        env="test",
        llm_provider="gemini",
        gemini_api_key="gk",
        llm_fallback_provider="openai",
        openai_api_key="ok",
    )
    fb = get_fallback_provider(settings)
    assert fb is not None
    assert fb.name == "openai"


async def test_fallback_missing_api_key_returns_none() -> None:
    settings = Settings(
        env="test",
        llm_provider="gemini",
        gemini_api_key="gk",
        llm_fallback_provider="openai",
        openai_api_key=None,
    )
    fb = get_fallback_provider(settings)
    assert fb is None


async def test_fallback_same_as_primary_returns_none() -> None:
    settings = Settings(
        env="test",
        llm_provider="gemini",
        gemini_api_key="gk",
        llm_fallback_provider="gemini",
    )
    fb = get_fallback_provider(settings)
    assert fb is None


async def test_fallback_empty_string_returns_none() -> None:
    settings = Settings(
        env="test", llm_provider="gemini", gemini_api_key="gk", llm_fallback_provider=""
    )
    fb = get_fallback_provider(settings)
    assert fb is None
