"""A6-07: the provider contract fixtures replay every real response shape.

The audit's remaining A6-07 gap was TRUNCATION: error, safety-block and
empty-candidate payloads were replayed, but a completion cut off by the output
token ceiling had no fixture. Replayed here for both real providers against a
MockTransport, using the vendors' documented shapes:

* Gemini ``finishReason: "MAX_TOKENS"`` with partial text (ai.google.dev/api/
  generate-content) -- the partial text is returned and the truncation is
  logged as ``provider_response_truncated``, never silent;
* OpenAI ``finish_reason: "length"`` with partial text (platform.openai.com/
  docs/api-reference/chat) -- same contract;
* the neighbouring shapes stay pinned in one table: safety block and empty
  candidates raise ProviderError with the finish reason named.

Bengali literals are Unicode escapes only (repo rule for new files).
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.providers.gemini import GeminiProvider
from bangla_gpt_api.providers.openai import OpenAIProvider

PARTIAL = "\u09aa\u09cd\u09b0\u09a5\u09ae \u09ac\u09be\u0995\u09cd\u09af"  # one cut-off sentence


def _gemini(payload: dict) -> GeminiProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    return GeminiProvider(
        api_key="k",
        model="gemini-2.5-flash",
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )


def _openai(payload: dict) -> OpenAIProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    return OpenAIProvider(
        api_key="k",
        model="gpt-4o-mini",
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )


async def test_gemini_max_tokens_returns_partial_text_and_logs_truncation(caplog) -> None:
    provider = _gemini(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": PARTIAL}], "role": "model"},
                    "finishReason": "MAX_TOKENS",
                }
            ],
            "usageMetadata": {"totalTokenCount": 2048},
        }
    )
    with caplog.at_level(logging.WARNING, logger="bangla_gpt_api.providers.gemini"):
        answer = await provider.generate("q")
    assert answer == PARTIAL
    assert "provider_response_truncated" in caplog.text
    record = json.loads(caplog.records[-1].message)
    assert record["event"] == "provider_response_truncated"
    assert record["finish_reason"] == "MAX_TOKENS"


async def test_gemini_safety_block_without_text_raises(caplog) -> None:
    provider = _gemini({"candidates": [{"finishReason": "SAFETY"}]})
    with pytest.raises(ProviderError, match=r"no text|no candidates"):
        await provider.generate("q")


async def test_gemini_empty_candidates_raise() -> None:
    provider = _gemini({"candidates": []})
    with pytest.raises(ProviderError, match="no candidates"):
        await provider.generate("q")


async def test_openai_length_returns_partial_text_and_logs_truncation(caplog) -> None:
    provider = _openai(
        {
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "message": {"role": "assistant", "content": PARTIAL},
                    "finish_reason": "length",
                }
            ],
        }
    )
    with caplog.at_level(logging.WARNING, logger="bangla_gpt_api.providers.openai"):
        answer = await provider.generate("q")
    assert answer == PARTIAL
    assert "provider_response_truncated" in caplog.text
    record = json.loads(caplog.records[-1].message)
    assert record["finish_reason"] == "length"


async def test_openai_content_filter_without_text_raises() -> None:
    provider = _openai(
        {
            "choices": [
                {"message": {"role": "assistant", "content": ""}, "finish_reason": "content_filter"}
            ]
        }
    )
    with pytest.raises(ProviderError, match="finishReason=content_filter"):
        await provider.generate("q")


async def test_openai_empty_choices_raise() -> None:
    provider = _openai({"choices": []})
    with pytest.raises(ProviderError, match="no choices"):
        await provider.generate("q")


async def test_a_stop_finish_reason_never_logs_truncation(caplog) -> None:
    provider = _gemini(
        {
            "candidates": [
                {"content": {"parts": [{"text": PARTIAL}], "role": "model"}, "finishReason": "STOP"}
            ]
        }
    )
    with caplog.at_level(logging.WARNING, logger="bangla_gpt_api.providers.gemini"):
        assert await provider.generate("q") == PARTIAL
    assert "provider_response_truncated" not in caplog.text
