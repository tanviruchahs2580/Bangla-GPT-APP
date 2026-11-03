"""Remote embedder contract (audit F-01/C2).

The factory arm that accepts a real multilingual embedding model without
changing a single retrieval call site: naming EMBEDDING_MODEL with an
endpoint+key yields an OpenAI-compatible batching client satisfying the
same contract the local hashing stand-in documents (fixed dimension,
input-ordered batches, L2-normalisation on the way out). Every transport
behaviour below is pinned against httpx.MockTransport — no live endpoint
anywhere in the suite.
"""

from __future__ import annotations

import json
import math

import httpx
import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.providers.base import ProviderError, ProviderNotConfigured
from bangla_gpt_api.retrieval.embedding import (
    HashingEmbedder,
    RemoteEmbedder,
    build_embedder,
)


def _settings(**overrides: str) -> Settings:
    return Settings(env="test", **overrides)


def _endpoint(vectors: list[list[float]], status: int = 200, fail_first: int = 0):
    """A handler that fails the first ``fail_first`` calls, then answers."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= fail_first:
            return httpx.Response(503, text="upstream sad")
        body = json.loads(request.content.decode())
        inputs = body["input"]
        assert body["encoding_format"] == "float"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": i, "embedding": vectors[i % len(vectors)]} for i in range(len(inputs))
                ]
            },
        )

    return handler


def _embedder(handler) -> RemoteEmbedder:
    return RemoteEmbedder(
        model="test-embed",
        api_base="https://embed.example.com/v1",
        api_key="ek",
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )


def test_factory_local_lane_when_model_empty() -> None:
    assert isinstance(build_embedder(_settings()), HashingEmbedder)


def test_factory_rejects_model_without_backend() -> None:
    with pytest.raises(ProviderNotConfigured):
        build_embedder(_settings(embedding_model="multilingual-e5-base"))


def test_factory_builds_remote_embedder_with_backend() -> None:
    embedder = build_embedder(
        _settings(
            embedding_model="multilingual-e5-base",
            embedding_api_base="https://embed.example.com/v1",
            embedding_api_key="ek",
        )
    )
    assert isinstance(embedder, RemoteEmbedder)
    assert embedder.name == "remote:multilingual-e5-base"


def test_embed_batches_in_input_order_and_l2_normalises() -> None:
    # two batches (batch_size 2 of 3 texts) off one constant vector
    embedder = _embedder(_endpoint([[3.0, 4.0]]))
    embedder._batch_size = 2
    vectors = embedder.embed(["এক", "দুই", "তিন"])
    assert len(vectors) == 3
    for vector in vectors:
        assert math.isclose(sum(v * v for v in vector), 1.0, rel_tol=1e-9)
        assert vector[0] == pytest.approx(0.6)
        assert vector[1] == pytest.approx(0.8)
    assert embedder.dim == 2


def test_embed_retries_retryable_then_succeeds() -> None:
    embedder = _embedder(_endpoint([[1.0, 0.0]], fail_first=1))
    vectors = embedder.embed(["প্রশ্ন"])
    assert vectors == [[1.0, 0.0]]


def test_embed_raises_after_exhausted_retries() -> None:
    embedder = _embedder(_endpoint([[1.0, 0.0]], fail_first=99))
    embedder._timeout = 0.01
    with pytest.raises(ProviderError):
        embedder.embed(["প্রশ্ন"])


def test_embed_rejects_dimension_drift() -> None:
    handler_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        handler_calls["n"] += 1
        vector = [1.0, 0.0] if handler_calls["n"] == 1 else [1.0, 0.0, 0.0]
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]})

    embedder = _embedder(handler)
    embedder.embed(["এক"])
    with pytest.raises(ProviderError, match="dimensions"):
        embedder.embed(["দুই"])


def test_embed_rejects_malformed_payload() -> None:
    embedder = _embedder(lambda request: httpx.Response(200, json={"data": ["junk"]}))
    with pytest.raises(ProviderError):
        embedder.embed(["প্রশ্ন"])
