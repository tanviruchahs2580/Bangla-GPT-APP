"""Shared retrieval contracts (S4.3 RAG v2).

Both lanes -- :class:`BM25Index` (lexical) and :class:`HybridIndex`
(BM25+vector+RRF+rerank) -- satisfy this structural protocol, so services
depend on the contract, not a concrete index.
"""

from typing import Protocol

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.retrieval.bm25 import Hit


class RankingIndex(Protocol):
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
