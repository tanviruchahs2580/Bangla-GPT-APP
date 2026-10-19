"""Shared retrieval contracts (RAG v2).

Both lanes --:class:`BM25Index` (lexical) and:class:`HybridIndex`
(BM25+vector+RRF+rerank) -- satisfy this structural protocol, so services
depend on the contract, not a concrete index. The filter schema lives in
:mod:`bangla_gpt_api.retrieval.filters` (leaf module, no cycles).
"""

from __future__ import annotations

from typing import Protocol

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.retrieval.filters import SearchFilters, chunk_matches_filters

__all__ = ["RankingIndex", "SearchFilters", "chunk_matches_filters"]


class RankingIndex(Protocol):
    """The baseline search contract every index satisfies.

    The concrete lanes (``BM25Index``, ``VectorIndex``, ``HybridIndex``)
    additionally accept the ``content_type`` and ``version`` pre-filters
    documented in :mod:`bangla_gpt_api.retrieval.filters`; the decorator in
    ``caching.py`` implements this baseline signature, so the extension is
    typed on the concrete classes rather than forced onto every decorator.
    """

    chunks: list[Chunk]

    def search(
        self,
        query: str,
        *,
        class_level: int | None = None,
        subject: str | None = None,
        chapter: str | None = None,
        top_k: int = 4,
        min_score: float = 0.0,
    ) -> list[Hit]: ...
