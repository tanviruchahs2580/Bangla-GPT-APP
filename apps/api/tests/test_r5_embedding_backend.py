"""A4-02: the embedding-backend seam and the Gemini adapter's contract.

Pinned here, all hermetic (no network: the adapter takes an injected
transport):

* ``build_embedder`` returns the deterministic hashing lane with an empty
  ``EMBEDDING_MODEL``, the Gemini adapter for a supported model name with a
  key, and raises for everything else — a named model must never degrade
  silently to the hashing lane;
* the adapter satisfies the ``Embedder`` protocol (``name`` + ``embed``) and
  returns vectors in input order, one per text;
* batching: 150 texts become two requests (100 + 50), and the request bodies
  carry the model, the requested dimensionality and the text;
* the input ceiling: a text whose token estimate exceeds the reference's
  2 048-token limit is truncated before the call, and an empty text is sent as
  a placeholder (the API rejects empty parts);
* a 429 uses the vendor's ``Retry-After`` hint and a later success still
  returns the vectors (a rate-limited run must make progress, not die);
* a response with the wrong number of vectors raises ``ProviderError`` rather
  than returning a mis-aligned list.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.providers.base import ProviderError, ProviderNotConfigured
from bangla_gpt_api.retrieval.embedding import HashingEmbedder, build_embedder
from bangla_gpt_api.retrieval.gemini_embedder import (
    MAX_BATCH_SIZE,
    MAX_INPUT_TOKENS,
    GeminiEmbedder,
)


class _Response:
    def __init__(self, status_code: int, payload: dict, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = str(payload)[:200]

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected raise_for_status on {self.status_code}")


class _Transport:
    """Records every request; answers 429 once when told to."""

    def __init__(self, *, sizes: list[int], rate_limit_first: bool = False) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.sizes = sizes
        self.rate_limit_first = rate_limit_first
        self.calls = 0

    def post(self, url: str, **kwargs: object) -> _Response:
        payload = dict(kwargs.get("json") or {})
        self.requests.append((url, payload))
        self.calls += 1
        if self.rate_limit_first and self.calls == 1:
            return _Response(429, {"error": {"code": 429}}, headers={"retry-after": "1"})
        count = self.sizes[min(len(self.requests) - 1, len(self.sizes) - 1)]
        return _Response(
            200,
            {"embeddings": [{"values": [0.1, 0.2, 0.3]} for _ in range(count)]},
        )


def test_build_embedder_selects_by_configuration_only() -> None:
    assert isinstance(build_embedder(Settings(env="test")), HashingEmbedder)
    chosen = build_embedder(
        Settings(env="test", embedding_model="gemini-embedding-001", gemini_api_key="k")
    )
    assert isinstance(chosen, GeminiEmbedder)
    assert chosen.name == "gemini:gemini-embedding-001"
    with pytest.raises(ProviderNotConfigured):
        build_embedder(Settings(env="test", embedding_model="some-local-model"))
    with pytest.raises(ProviderNotConfigured):
        build_embedder(Settings(env="test", embedding_model="gemini-embedding-001"))
    with pytest.raises(ProviderError):
        GeminiEmbedder(api_key="")


def test_batches_by_hundreds_and_preserves_order() -> None:
    transport = _Transport(sizes=[MAX_BATCH_SIZE, 50])
    embedder = GeminiEmbedder(api_key="k", transport=transport)
    texts = [f"পাঠ {index}" for index in range(150)]
    vectors = embedder.embed(texts)
    assert len(vectors) == 150
    assert all(vector == [0.1, 0.2, 0.3] for vector in vectors)
    assert len(transport.requests) == 2
    url, payload = transport.requests[1]
    assert url.endswith("models/gemini-embedding-001:batchEmbedContents")
    assert len(payload["requests"]) == 50
    first = payload["requests"][0]
    assert first["model"] == "models/gemini-embedding-001"
    assert first["outputDimensionality"] == 768
    assert first["content"]["parts"][0]["text"] == "পাঠ 100"


def test_input_ceiling_truncates_and_empty_text_gets_a_placeholder() -> None:
    transport = _Transport(sizes=[2])
    embedder = GeminiEmbedder(api_key="k", transport=transport)
    long_text = " ".join(["শব্দ"] * 5000)
    embedder.embed([long_text, "   "])
    sent = transport.requests[0][1]["requests"]
    truncated = sent[0]["content"]["parts"][0]["text"]
    assert len(truncated.split(" ")) < 5000
    assert sent[1]["content"]["parts"][0]["text"] == "(empty)"


def test_rate_limit_is_retried_with_the_vendor_hint() -> None:
    transport = _Transport(sizes=[1], rate_limit_first=True)
    embedder = GeminiEmbedder(api_key="k", transport=transport, min_interval_seconds=0)
    assert embedder.embed(["একটি"]) == [[0.1, 0.2, 0.3]]
    assert transport.calls == 2, "the 429 is retried, not surfaced as a failure"


def test_vector_count_mismatch_is_a_provider_error() -> None:
    transport = _Transport(sizes=[1])
    embedder = GeminiEmbedder(api_key="k", transport=transport)
    with pytest.raises(ProviderError):
        embedder.embed(["এক", "দুই"])


def test_token_ceiling_constant_matches_the_documented_reference() -> None:
    # The module docstring cites the reference's 2 048-token ceiling; the
    # constant is what the truncation uses, so the two cannot drift.
    assert MAX_INPUT_TOKENS == 2048
