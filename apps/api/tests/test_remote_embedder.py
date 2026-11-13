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


def test_embed_raises_on_non_retryable_status() -> None:
    embedder = _embedder(lambda request: httpx.Response(401, text="bad key"))
    with pytest.raises(ProviderError, match="401"):
        embedder.embed(["প্রশ্ন"])


def test_embed_rejects_non_numeric_vector() -> None:
    embedder = _embedder(
        lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": ["x"]}]})
    )
    with pytest.raises(ProviderError, match="non-numeric"):
        embedder.embed(["প্রশ্ন"])


def test_embed_raises_on_malformed_row() -> None:
    embedder = _embedder(lambda request: httpx.Response(200, json={"data": ["junk"]}))
    with pytest.raises(ProviderError, match="malformed"):
        embedder.embed(["প্রশ্ন"])


def test_embed_rejects_vector_count_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    embedder = _embedder(handler)
    with pytest.raises(ProviderError, match="vectors for"):
        embedder.embed(["এক", "দুই"])  # 2 inputs, endpoint returns 1 vector


def _write_manifest(tmp_path, *, dim: int) -> None:
    """A corpus manifest whose derived embedder record declares `dim`."""
    from bangla_gpt_api.nctb.manifest import CORPUS_MANIFEST_NAME

    (tmp_path / "manifests").mkdir(parents=True, exist_ok=True)
    manifest = {"derived": {"embedder": {"name": "remote:test-model", "dim": dim}}}
    (tmp_path / "manifests" / CORPUS_MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )


class _T(httpx.BaseTransport):
    """Serves 3-dimensional vectors for every embed call."""

    def handle_request(self, request):
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})


def _late_check_factory(expected_dim: int):
    from bangla_gpt_api.providers.base import ProviderNotConfigured

    def check(dim: int) -> None:
        if dim != expected_dim:
            raise ProviderNotConfigured(
                f"embedder dim: manifest {expected_dim} != configured {dim}"
            )

    return check


def test_remote_dim_mismatch_refuses_after_the_first_embed(tmp_path) -> None:
    """Audit F-3: the remote lane discovers its dimension from the FIRST
    response, and the manifest check ran at build time when dim was still
    None — the dim leg of the identity check was dead for remote embedders.
    The on_dim_known hook must fire once the dimension becomes known."""
    from bangla_gpt_api.providers.base import ProviderNotConfigured
    from bangla_gpt_api.retrieval.embedding import RemoteEmbedder

    _write_manifest(tmp_path, dim=512)
    embedder = RemoteEmbedder(
        model="test-model",
        api_base="http://embed.test",
        api_key="k",
        transport=_T(),
        on_dim_known=_late_check_factory(512),
    )
    assert embedder.dim is None
    with pytest.raises(ProviderNotConfigured, match="embedder dim"):
        embedder.embed(["কোষ কী?"])


def test_remote_dim_match_serves_after_the_first_embed(tmp_path) -> None:
    from bangla_gpt_api.retrieval.embedding import RemoteEmbedder

    _write_manifest(tmp_path, dim=3)
    embedder = RemoteEmbedder(
        model="test-model",
        api_base="http://embed.test",
        api_key="k",
        transport=_T(),
        on_dim_known=_late_check_factory(3),
    )
    vectors = embedder.embed(["কোষ কী?"])
    assert len(vectors[0]) == 3


def test_build_embedder_installs_the_late_dim_check(tmp_path) -> None:
    """The factory wires the hook whenever a corpus dir exists, so the dim
    leg cannot stay dead in the production path."""
    from bangla_gpt_api.retrieval.embedding import RemoteEmbedder, build_embedder

    _write_manifest(tmp_path, dim=3)
    settings = type(
        "S",
        (),
        {
            "embedding_model": "test-model",
            "embedding_api_base": "http://embed.test",
            "embedding_api_key": "k",
            "nctb_corpus_dir": str(tmp_path),
        },
    )()
    embedder = build_embedder(settings)
    assert isinstance(embedder, RemoteEmbedder)
    assert embedder.on_dim_known is not None


def test_late_dim_check_is_a_noop_without_a_corpus_dir(tmp_path) -> None:
    """No corpus dir configured: the late leg has nothing to compare."""
    from bangla_gpt_api.retrieval.embedding import RemoteEmbedder, build_embedder

    settings = type("S", (), {"embedding_model": "test-model",
                              "embedding_api_base": "http://embed.test",
                              "embedding_api_key": "k", "nctb_corpus_dir": ""})()
    embedder = build_embedder(settings)
    assert isinstance(embedder, RemoteEmbedder)
    embedder.on_dim_known(3)  # must not raise


def test_late_dim_check_is_a_noop_when_the_manifest_is_absent(tmp_path) -> None:
    """A corpus dir without a manifest predates the embedder record — not a
    mismatch (index_manifest.embedder_problems documents the same rule)."""
    from bangla_gpt_api.retrieval.embedding import RemoteEmbedder, build_embedder

    settings = type("S", (), {"embedding_model": "test-model",
                              "embedding_api_base": "http://embed.test",
                              "embedding_api_key": "k",
                              "nctb_corpus_dir": str(tmp_path)})()
    embedder = build_embedder(settings)
    embedder.on_dim_known(3)  # must not raise


def test_late_dim_check_uses_the_corpus_dir_captured_at_build(tmp_path) -> None:
    """The hook keeps the corpus dir from build time (default-arg binding);
    a mismatch raises through embed() where the hook fires."""
    from bangla_gpt_api.providers.base import ProviderNotConfigured
    from bangla_gpt_api.retrieval.embedding import RemoteEmbedder, build_embedder

    _write_manifest(tmp_path, dim=512)
    settings = type("S", (), {"embedding_model": "test-model",
                              "embedding_api_base": "http://embed.test",
                              "embedding_api_key": "k",
                              "nctb_corpus_dir": str(tmp_path)})()
    embedder = build_embedder(settings)
    with pytest.raises(ProviderNotConfigured, match="different embedder"):
        embedder.on_dim_known(3)


def test_l2_normalize_passes_a_zero_vector_through_untouched() -> None:
    """A zero vector has no direction to normalize; dividing would NaN."""
    from bangla_gpt_api.retrieval.embedding import _l2_normalize

    assert _l2_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_parse_refuses_a_non_object_payload() -> None:
    from bangla_gpt_api.providers.base import ProviderError
    from bangla_gpt_api.retrieval.embedding import RemoteEmbedder

    embedder = _embedder(lambda request: httpx.Response(200, json={"data": []}))
    with pytest.raises(ProviderError, match="non-object payload"):
        embedder._parse("not-an-object", expected=1)


def test_verify_embedder_identity_is_a_noop_when_the_manifest_is_absent(tmp_path) -> None:
    """A corpus dir without a manifest predates the embedder record — not a
    mismatch (same rule index_manifest.embedder_problems documents)."""
    from bangla_gpt_api.retrieval.embedding import _verify_embedder_identity, build_embedder

    settings = type("S", (), {"embedding_model": "", "nctb_corpus_dir": str(tmp_path)})()
    embedder = build_embedder(settings)
    _verify_embedder_identity(settings, embedder)  # must not raise
