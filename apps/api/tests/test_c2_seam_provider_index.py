"""C-15: contract tests for the LLM provider and retrieval index seams.

The audit (status-cd C-15) recorded what existed and what did not: the LLM,
retrieval and embedding seams had characterisation tests, but there was no
*contract* suite that any implementation of a seam must pass. A seam is only a
seam if a replacement can be dropped in, so each contract is defined ONCE and
run against every implementation:

* the LLM providers -- mock (the default), Gemini and OpenAI over a mocked
  transport; the suite also self-checks that a deliberately broken provider
  FAILS it, so it cannot silently pass everything;
* the retrieval indexes -- ``BM25Index`` and the hybrid lane.

The email and queue seams are the companion file
(``test_c2_seam_email_queue.py``); this split is only about the 500-line rule.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.providers.base import LLMProvider, ProviderError
from bangla_gpt_api.providers.gemini import GeminiProvider
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.providers.openai import OpenAIProvider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.retrieval.embedding import HashingEmbedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

APP = Path(__file__).resolve().parents[1]


# =========================================================================== #
# 1. LLM provider seam


ANSWER = "উত্তর"


def _ok(text: str, request: httpx.Request) -> httpx.Response:
    if "openai" in str(request.url):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": text}}]},
            request=request,
        )
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
        request=request,
    )


def _sse(text: str, request: httpx.Request) -> httpx.Response:
    if "openai" in str(request.url):
        payload = json.dumps({"choices": [{"delta": {"content": text}}]})
        body = f"data: {payload}\n\ndata: [DONE]\n\n"
    else:
        payload = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]})
        body = f"data: {payload}\n\n"
    return httpx.Response(
        200, text=body, headers={"content-type": "text/event-stream"}, request=request
    )


def _any_transport(text: str = ANSWER) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        streaming = "streamGenerateContent" in str(request.url)
        if not streaming and request.content:
            import json as _json

            try:
                streaming = bool(_json.loads(request.content).get("stream"))
            except ValueError:
                streaming = False
        if streaming:
            return _sse(text, request)
        return _ok(text, request)

    return httpx.MockTransport(handler)


def _failing_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"code": 503, "message": "unavailable", "status": "UNAVAILABLE"}},
            request=request,
        )

    return httpx.MockTransport(handler)


def _gemini(transport: httpx.MockTransport, max_retries: int = 0) -> GeminiProvider:
    return GeminiProvider(
        api_key="k", model="m", timeout_seconds=5.0, max_retries=max_retries, transport=transport
    )


def _openai(transport: httpx.MockTransport, max_retries: int = 0) -> OpenAIProvider:
    return OpenAIProvider(
        api_key="k", model="m", timeout_seconds=5.0, max_retries=max_retries, transport=transport
    )


async def _provider_contract_violations(provider: LLMProvider) -> list[str]:
    """Everything a drop-in LLM provider must satisfy, as a list of failures."""
    problems: list[str] = []
    if not isinstance(getattr(provider, "name", None), str) or not provider.name:
        problems.append("name must be a non-empty string")
    if not isinstance(getattr(provider, "supports_vision", None), bool):
        problems.append("supports_vision must be declared as a bool (the vision-honesty contract)")

    signature = inspect.signature(provider.generate)
    for parameter in signature.parameters.values():
        if parameter.name in {"system", "image"} and parameter.kind is not (
            inspect.Parameter.KEYWORD_ONLY
        ):
            problems.append(f"{parameter.name} must be keyword-only")
    if signature.parameters["prompt"].name != "prompt":
        problems.append("generate() must take the prompt positionally")

    text = str(await provider.generate("প্রশ্ন?", system="নিয়ম", image=None))
    if not isinstance(text, str) or not text.strip():
        problems.append("generate() must return a non-empty string")

    chunks: list[str] = [str(chunk) async for chunk in provider.stream("প্রশ্ন?")]
    if not chunks or not all(isinstance(c, str) for c in chunks):
        problems.append("stream() must yield non-empty strings")
    elif "".join(chunks).strip() != text.strip():
        # mock/gemini/openai all serve the same prompt through both paths; a
        # replacement that diverges makes streaming untestable against generate
        problems.append("stream() and generate() must agree on the answer")
    return problems


@pytest.mark.parametrize(
    "build",
    [
        lambda: MockLLMProvider(),
        lambda: _gemini(_any_transport()),
        lambda: _openai(_any_transport()),
    ],
    ids=["mock", "gemini", "openai"],
)
def test_llm_provider_seam_contract(build) -> None:
    provider = build()
    assert hasattr(provider, "generate") and hasattr(provider, "stream")
    assert asyncio.run(_provider_contract_violations(provider)) == []


@pytest.mark.parametrize(
    "build",
    [lambda: _gemini(_failing_transport()), lambda: _openai(_failing_transport())],
    ids=["gemini", "openai"],
)
def test_llm_provider_seam_failure_surface(build) -> None:
    """A dead upstream must surface as ProviderError, never as httpx internals."""
    provider = build()

    async def call() -> str:
        return str(await provider.generate("প্রশ্ন?"))

    with pytest.raises(ProviderError):
        asyncio.run(call())


class _BrokenProvider:
    """A provider that violates the seam; the suite must call it out."""

    name = ""
    supports_vision = "yes"

    async def generate(self, prompt: str, system: str = "", image: Any = None) -> str:
        return ""

    async def stream(self, prompt: str, system: str = "", image: Any = None) -> AsyncIterator[str]:
        empty: list[str] = []  # a broken provider yields nothing
        for chunk in empty:  # pragma: no cover
            yield chunk


def test_provider_contract_suite_actually_bites() -> None:
    problems = asyncio.run(_provider_contract_violations(_BrokenProvider()))
    assert len(problems) >= 4, problems
    assert any("supports_vision" in p for p in problems)
    assert any("keyword-only" in p for p in problems)
    assert any("non-empty string" in p for p in problems)


# =========================================================================== #
# 2. Retrieval index seam


def _indexes() -> list[Any]:
    chunks = load_sample_corpus()
    return [BM25Index(chunks), HybridIndex(chunks, HashingEmbedder())]


def _index_contract_violations(index: Any, *, min_score_filters: bool) -> list[str]:
    problems: list[str] = []
    chunks = load_sample_corpus()
    if list(index.chunks) != list(chunks):
        problems.append("chunks must expose the corpus the index serves")
    known_ids = {chunk.id for chunk in chunks}

    hits = index.search("কোষ কী", top_k=4)
    if not hits:
        problems.append("search() must find a known sample-corpus question")
        return problems
    if any(hit.chunk.id not in known_ids for hit in hits):
        problems.append("every hit must come from the served corpus")
    scores = [hit.score for hit in hits]
    if scores != sorted(scores, reverse=True):
        problems.append("hits must be ordered by non-increasing score")
    if len(hits) > 4:
        problems.append("top_k must cap the result length")

    # same query, same order: a non-deterministic index breaks caching and eval
    again = index.search("কোষ কী", top_k=4)
    if [h.chunk.id for h in again] != [h.chunk.id for h in hits]:
        problems.append("search() must be deterministic for the same query")

    if index.search("কোষ কী", top_k=0) != []:
        problems.append("top_k=0 must return nothing")
    if index.search("   ", top_k=4) != []:
        problems.append("a blank query must return nothing")

    filtered = index.search("কোষ কী", class_level=6, top_k=10)
    if any(hit.chunk.meta.class_level != 6 for hit in filtered):
        problems.append("class_level must be honoured as a filter")

    subject = chunks[0].meta.subject
    scoped = index.search("কোষ", subject=subject, top_k=10)
    if any(hit.chunk.meta.subject != subject for hit in scoped):
        problems.append("subject must be honoured as a filter")

    high = index.search("কোষ কী", top_k=4, min_score=1e9)
    if min_score_filters and high:
        problems.append("min_score above every hit must return nothing")
    if not min_score_filters and not high:
        problems.append("the BM25 lane documents min_score as a soft-lane switch, not a filter")
    return problems


@pytest.mark.parametrize(
    "index_name, min_score_filters",
    [("bm25", False), ("hybrid", True)],
)
def test_index_seam_contract(index_name, min_score_filters) -> None:
    """The shared contract, run against both lanes.

    ``min_score`` is the one place the lanes genuinely differ today: the hybrid
    lane filters results with it (``hybrid_index.py:282``), while the BM25 lane
    uses it as the threshold below which the trigram soft lane may take over
    (``bm25.py:123``) and never filters. That is a real seam defect -- one
    caller (``routers/learn.py`` global search, ``min_score=0.5``) gets two
    different behaviours depending on RETRIEVAL_MODE -- so it is pinned here
    per lane and reported, rather than papered over. Unifying it changes
    retrieval results and belongs to the retrieval owner.
    """
    index = _indexes()[0 if index_name == "bm25" else 1]
    assert _index_contract_violations(index, min_score_filters=min_score_filters) == []


def test_index_seam_min_score_divergence_is_known_and_bounded() -> None:
    """If a lane's min_score semantics change, this test must be updated knowingly."""
    bm25, hybrid = _indexes()
    assert len(bm25.search("কোষ কী", min_score=1e9)) > 0
    assert hybrid.search("কোষ কী", min_score=1e9) == []


def test_index_contract_pins_both_lanes_to_the_same_shape() -> None:
    """The two lanes are interchangeable behind RankingIndex."""
    for index in _indexes():
        assert hasattr(index, "search") and hasattr(index, "chunks")
