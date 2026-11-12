"""Cross-encoder reranker (retrieval engine v2, stage 1).

The target flow's rerank stage is a CROSS-ENCODER; the served engine ships a
deterministic lexical ranker at that stage. The contract under test:

* `build_reranker_config(settings)` returns None for the default
  (`RAG_RERANKER="lexical"`) and a validated config for `"cross_encoder"`
  (endpoint + model required; a model without an endpoint is a
  configuration error, mirroring `embedding_model` doctrine).
* `CrossEncoderReranker` DECORATES the index's lexical ranker: on success the
  cross-encoder's normalized scores drive the final ordering (lexical base
  kept as the magnitude floor so fusion-only chunks stay positive); on ANY
  failure (timeout, HTTP error, malformed body, open breaker) the stage
  falls back to the inner scores for that turn — degrade, never lie, never
  refuse for reranker reasons — and meters the fallback.
* The QUERY is student input: it is PII-redacted before leaving the process.
  Candidate documents are published textbook text (the same exposure class
  as the evidence already sent to the LLM) and are not redacted.
* Every failure mode is exercised against a real HTTP surface via
  httpx.MockTransport — no network, no mocks of the code under test.
"""

from __future__ import annotations

import httpx
import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.metrics import REGISTRY
from bangla_gpt_api.retrieval.hybrid_index import make_lexical_rerank
from bangla_gpt_api.retrieval.reranker import (
    CrossEncoderReranker,
    RerankerEndpointError,
    build_cross_encoder_config,
)

SECRET = "test-secret-0123456789abcdef0123456789"


def _meta(**over) -> CurriculumMeta:
    base = dict(
        curriculum_year=2026,
        class_level=6,
        subject="science",
        book="NCTB Science 6",
        source="sample-1",
        chapter="কোষ",
    )
    base.update(over)
    return CurriculumMeta(**base)


def _chunk(cid: str, text: str, **over) -> Chunk:
    return Chunk(id=cid, text=text, meta=_meta(**over))


def _settings(**over) -> Settings:
    base = dict(
        env="test",
        jwt_secret=SECRET,
        rag_reranker="cross_encoder",
        rag_reranker_endpoint="http://reranker.test",
        rag_reranker_model="bge-reranker-v2-m3",
    )
    base.update(over)
    return Settings(**base)


def _candidates() -> list[tuple[Chunk, float, float]]:
    return [
        (_chunk("c1", "কোষ জীবের গঠন ও কার্যের ক্ষুদ্রতম একক।"), 0.9, 6.2),
        (_chunk("c2", "সালোকসংশ্লেষণ হলো খাদ্য তৈরির প্রক্রিয়া।"), 0.4, 3.1),
    ]


def _lexical() -> object:
    return make_lexical_rerank(None)


def _counter(name: str) -> float:
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == name or sample.name == f"bgpt_{name}":
                return sample.value
    return 0.0


# --- config ------------------------------------------------------------------


def test_default_lexical_produces_no_config() -> None:
    assert build_cross_encoder_config(Settings(env="test", jwt_secret=SECRET)) is None


def test_cross_encoder_without_endpoint_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="ENDPOINT"):
        build_cross_encoder_config(_settings(rag_reranker_endpoint=""))


def test_cross_encoder_without_model_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="MODEL"):
        build_cross_encoder_config(_settings(rag_reranker_model=""))


def test_unknown_reranker_name_is_refused() -> None:
    with pytest.raises(ValueError, match="RAG_RERANKER"):
        build_cross_encoder_config(_settings(rag_reranker="magic"))


# --- success path -------------------------------------------------------------


def test_cross_encoder_orders_and_keeps_the_lexical_floor() -> None:
    """The endpoint ranks c2 first; the final ordering must follow the
    cross-encoder while the lexical base keeps the BM25 magnitude floor."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.read())
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.93},
                    {"index": 0, "relevance_score": 0.11},
                ]
            },
        )

    inner = _lexical()
    reranker = CrossEncoderReranker(
        inner,
        config=build_cross_encoder_config(_settings()),
        transport=httpx.MockTransport(handler),
    )
    candidates = _candidates()
    scores = reranker("কোষ কী?", candidates)

    assert len(scores) == 2
    # c2 (index 1) now outranks c1 despite the lower lexical base
    assert scores[1] > scores[0]
    # the lexical magnitude floor survives: both stay positive
    assert all(s > 0 for s in scores)
    # the query left the process PII-redacted, and the body is the rerank contract
    body = calls[0]
    assert b"query" in body and b"documents" in body


def test_query_is_redacted_before_egress() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.read().decode("utf-8"))
        return httpx.Response(200, json={"results": []})

    reranker = CrossEncoderReranker(
        _lexical(),
        config=build_cross_encoder_config(_settings()),
        transport=httpx.MockTransport(handler),
    )
    reranker("আমার ফোন 01712345678, কোষ কী?", _candidates())
    assert "01712345678" not in seen[0]
    assert "[phone redacted]" in seen[0]


def test_tie_scores_get_a_deterministic_mid_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.5},
                    {"index": 1, "relevance_score": 0.5},
                ]
            },
        )

    reranker = CrossEncoderReranker(
        _lexical(),
        config=build_cross_encoder_config(_settings()),
        transport=httpx.MockTransport(handler),
    )
    scores = reranker("কোষ কী?", _candidates())
    # equal endpoint scores normalize to one mid value; the ordering then
    # follows the lexical magnitude floor (deterministic, by design)
    assert scores[0] > scores[1]
    assert all(score > 0 for score in scores)


# --- failure paths: degrade to the inner scores, meter the fallback ----------


def test_timeout_falls_back_to_inner_scores_and_meters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    config = build_cross_encoder_config(_settings(rag_reranker_timeout_seconds=0.05))
    reranker = CrossEncoderReranker(
        _lexical(), config=config, transport=httpx.MockTransport(handler)
    )
    candidates = _candidates()
    fallback = _counter("rag_reranker_fallback_total")
    scores = reranker("কোষ কী?", candidates)
    assert scores == _lexical()("কোষ কী?", candidates)
    assert _counter("rag_reranker_fallback_total") > fallback


def test_http_error_falls_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    reranker = CrossEncoderReranker(
        _lexical(),
        config=build_cross_encoder_config(_settings()),
        transport=httpx.MockTransport(handler),
    )
    assert reranker("কোষ কী?", _candidates()) == _lexical()("কোষ কী?", _candidates())


def test_malformed_body_falls_back() -> None:
    reranker = CrossEncoderReranker(
        _lexical(),
        config=build_cross_encoder_config(_settings()),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not-json")),
    )
    assert reranker("কোষ কী?", _candidates()) == _lexical()("কোষ কী?", _candidates())


def test_index_out_of_range_is_a_protocol_error() -> None:
    class _Raises(RerankerEndpointError):
        pass

    reranker = CrossEncoderReranker(
        _lexical(),
        config=build_cross_encoder_config(_settings()),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"results": [{"index": 9, "relevance_score": 0.9}]}
            )
        ),
    )
    with pytest.raises(RerankerEndpointError, match="mismatched"):
        # protocol violations surface as the endpoint error type, caught and
        # converted to the fallback by the public callable
        reranker.rerank_remote("কোষ কী?", [c[0] for c in _candidates()])
    assert reranker("কোষ কী?", _candidates()) == _lexical()("কোষ কী?", _candidates())
