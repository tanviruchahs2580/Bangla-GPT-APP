"""A5-01: the exact vendor token counter (countTokens path) and its fallback.

Pinned here:
* the Gemini REST ``countTokens`` request SHAPE (method/path/header/body) and
  the ``totalTokens`` parse -- against a mock transport, no network;
* None on any endpoint failure (the calibrated heuristic is the fallback);
* the ExactTokenCounter adapter: vendor count used when answered, the
  heuristic upper bound when not, with honest provenance counters;
* the mock provider's count_tokens IS the heuristic and says it is not a
  vendor measurement;
* the settings flag wires the tutor's evidence budget to the exact counter
  and the default stays off (production keeps the safe upper bound).
"""

from __future__ import annotations

import httpx

from bangla_gpt_api.config import Settings
from bangla_gpt_api.services.context import HeuristicTokenCounter

SECRET = "test-secret-0123456789abcdef0123456789"


def _settings(tmp_path, **over) -> Settings:
    base = dict(env="test", database_url=f"sqlite:///{tmp_path}/tokens.db", jwt_secret=SECRET)
    base.update(over)
    return Settings(**base)


def _gemini(transport: httpx.BaseTransport, model: str = "gemini-test-model") -> object:
    from bangla_gpt_api.providers.gemini import GeminiProvider

    return GeminiProvider(
        api_key="test-key-not-real",
        model=model,
        timeout_seconds=5.0,
        max_retries=1,
        transport=transport,
    )


def test_count_tokens_request_shape_and_parse() -> None:
    """Contract: POST ...:countTokens, key header, contents parts body."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["key_header"] = request.headers.get("x-goog-api-key")
        captured["body"] = request.read()
        return httpx.Response(200, json={"totalTokens": 4321})

    provider = _gemini(httpx.MockTransport(handler))
    total = provider.count_tokens("সালোকসংশ্লেষণ কী?", system="SYSTEM")
    assert total == 4321
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/models/gemini-test-model:countTokens")
    assert captured["key_header"] == "test-key-not-real"
    body = httpx.Request("POST", "http://x", content=captured["body"]).read()
    assert b'"totalTokens"' not in body  # request side carries no such field
    assert "সালোকসংশ্লেষণ কী?".encode() in body
    assert b"systemInstruction" in body  # the system prompt is part of the budget


def test_count_tokens_falls_back_to_none_on_any_failure() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"code": 503, "message": "unavailable"}})

    provider = _gemini(httpx.MockTransport(failing))
    assert provider.count_tokens("x") is None

    def bad_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    provider = _gemini(httpx.MockTransport(bad_json))
    assert provider.count_tokens("x") is None


def test_transport_error_returns_none_not_raise() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    provider = _gemini(httpx.MockTransport(boom))
    assert provider.count_tokens("x") is None


def test_exact_token_counter_uses_vendor_then_falls_back() -> None:
    from bangla_gpt_api.providers.token_counter import (
        ExactTokenCounter,
        provider_supports_count_tokens,
    )

    class Vendor:
        name = "vendor"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def count_tokens(self, text: str) -> int:
            self.calls.append(text)
            return 7

    vendor = Vendor()
    counter = ExactTokenCounter(vendor)
    assert counter.name == "vendor-countTokens"
    assert counter.count("") == 7
    assert counter.vendor_calls == 1 and counter.fallback_calls == 0
    assert not counter.fell_back

    class Broken:
        name = "broken"
        raised = 0

        def count_tokens(self, _text: str) -> int:
            self.raised += 1
            raise RuntimeError("endpoint down")

    heuristic = HeuristicTokenCounter()
    counter = ExactTokenCounter(Broken(), fallback=HeuristicTokenCounter())
    text = "কোষ বিভাজন কী?"
    assert counter.count(text) == heuristic.count(text), "fallback must be the upper bound"
    assert counter.fallback_calls == 1 and counter.fell_back

    class NoCounts:
        name = "nocounts"

    assert provider_supports_count_tokens(NoCounts()) is False
    assert provider_supports_count_tokens(Vendor()) is True
    assert provider_supports_count_tokens(None) is False


def test_mock_provider_count_is_the_honest_heuristic() -> None:
    from bangla_gpt_api.providers.mock import MockLLMProvider
    from bangla_gpt_api.services.context import HeuristicTokenCounter

    provider = MockLLMProvider()
    text = "কোষ বিভাজন কী? এটি জীববিজ্ঞানের একটি অধ্যায়।"
    heuristic = HeuristicTokenCounter()
    assert provider.count_tokens(text) == heuristic.count(text)
    assert provider.count_tokens("") == 0
    assert provider.count_tokens_is_vendor is False


def test_default_is_heuristic_and_the_flag_wires_the_exact_counter(tmp_path) -> None:
    """Production default: no counter (HeuristicTokenCounter path); flag: exact."""
    from bangla_gpt_api.data.loader import load_sample_corpus
    from bangla_gpt_api.initialize.dependencies import _build_tutor
    from bangla_gpt_api.providers.mock import MockLLMProvider
    from bangla_gpt_api.providers.token_counter import ExactTokenCounter
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    index = HybridIndex(load_sample_corpus(), HashingEmbedder())
    provider = MockLLMProvider()

    off = _build_tutor(index, provider, None, None, None, settings=_settings(tmp_path))
    assert off._token_counter is None, "the production default stays the heuristic upper bound"

    on = _build_tutor(
        index,
        provider,
        None,
        None,
        None,
        settings=_settings(tmp_path, llm_exact_token_counting=True),
    )
    assert isinstance(on._token_counter, ExactTokenCounter)
    assert on._token_counter.name == "mock-countTokens"
    # The mock's exact path measures with ceil semantics == the context heuristic.
    assert on._token_counter.count("কোষ কী?") == HeuristicTokenCounter().count("কোষ কী?")


def test_audit_reports_the_mock_as_non_vendor(tmp_path) -> None:
    """The calibration audit on the mock provider: honest, no fake vendor data."""
    from pathlib import Path

    from bangla_gpt_api.evaluation import token_audit
    from bangla_gpt_api.providers.mock import MockLLMProvider

    root = Path(__file__).resolve().parents[1]
    payload = token_audit.build_audit(
        settings=_settings(tmp_path),
        golden_path=root / "eval" / "golden_v2.json",
        sample=4,
        seed=7,
        provider=MockLLMProvider(),
    )
    assert payload["provider"] == "mock"
    assert payload["counter"] == "mock-countTokens"
    assert payload["vendor_endpoint"] is False
    assert payload["vendor_calls"] > 0 and payload["fallback_calls"] == 0
    assert payload["sample_size"] >= 1
    assert payload["ratio_summary"]["mean"] is not None
    for row in payload["samples"]:
        ratio = row["ratio_heuristic_over_measured"]
        assert ratio is not None and 0 < ratio < 10  # heuristic == measured on the mock


def test_exact_token_counting_defaults_off_in_settings() -> None:
    """The A5-01 settings flag: production default stays the safe upper bound."""
    settings = Settings(env="test")
    assert settings.llm_exact_token_counting is False
