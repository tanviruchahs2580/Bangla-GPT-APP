"""S4.3 RAG v2 -- hybrid retrieval index: BM25 + vector -> RRF -> rerank.

Pipeline (master spec 4.3): section chunking (TextIngester, chunk.meta.
section) -> embedder (retrieval/embedding.py) -> vector lane
(retrieval/vector.py) + lexical lane (BM25Index) -> reciprocal rank fusion
(retrieval/fusion.py) -> reranker -> top_k.

``search`` is signature-compatible with :meth:`BM25Index.search`, so the
hybrid index is a drop-in for TutorService/the generation retrievers. The
reranker is a deterministic lexical cross-check (stem coverage + char
trigrams + fusion evidence); a model-based reranker can replace just the
rerank stage later.
"""

from collections.abc import Callable, Iterable

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.retrieval.bm25 import BM25Index, Hit, tokenize
from bangla_gpt_api.retrieval.embedding import Embedder, bengali_bigrams
from bangla_gpt_api.retrieval.fusion import reciprocal_rank_fusion
from bangla_gpt_api.retrieval.hybrid import light_stem, trigram_similarity
from bangla_gpt_api.retrieval.vector import VectorIndex, vector_text

#: rerank(query, [(chunk, rrf_score, lexical_lane_base_score)]) -> final scores
Reranker = Callable[[str, list[tuple[Chunk, float, float]]], list[float]]

_RRF_K = 60
#: candidate pool per lane before fusion (RRF then trims)
_CANDIDATE_FACTOR = 3

# Final-score blend: fusion agreement is the base; lexical agreement with
# the query re-checks the vector lane's picks.
_W_RRF = 1.0
_W_COVERAGE = 0.5
_W_TRIGRAM = 0.3


def lexical_rerank(query: str, candidates: list[tuple[Chunk, float, float]]) -> list[float]:
    """Deterministic rerank: BM25-lane base + fusion + coverage + trigram.

    The BM25-lane score stays the magnitude base so hybrid scores live on
    the same scale as the v1 baseline (callers such as /search gate on it).
    A chunk that exists in NO lexical lane keeps a small fusion-only score:
    enough for the tutor's grounded flow, too small to fake evidence where
    a lexical search found none.
    """
    query_terms = {light_stem(t) for t in tokenize(query) if len(t) >= 2}
    scores: list[float] = []
    for chunk, rrf_score, lexical_base in candidates:
        if query_terms:
            chunk_terms = {light_stem(t) for t in tokenize(chunk.text)}
            coverage = sum(1 for t in query_terms if t in chunk_terms) / len(query_terms)
        else:
            coverage = 0.0
        tri = trigram_similarity(query, chunk.text)
        scores.append(lexical_base + _W_RRF * rrf_score + _W_COVERAGE * coverage + _W_TRIGRAM * tri)
    return scores


class HybridIndex:
    """BM25 + vector lanes fused by RRF, then reranked. BM25-shaped API."""

    def __init__(
        self,
        chunks: list[Chunk],
        embedder: Embedder,
        *,
        reranker: Reranker = lexical_rerank,
        rrf_k: int = _RRF_K,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.chunks = chunks
        self.bm25 = BM25Index(chunks, k1=k1, b=b)
        self.vector = VectorIndex(chunks, embedder)
        self.reranker = reranker
        self.rrf_k = rrf_k

    def search(
        self,
        query: str,
        *,
        class_level: int | None = None,
        subject: str | None = None,
        chapter: str | None = None,
        top_k: int = 4,
        min_score: float = 0.0,
    ) -> list[Hit]:
        candidate_k = max(top_k * _CANDIDATE_FACTOR, top_k + 1)
        bm25_hits = self.bm25.search(
            query,
            class_level=class_level,
            subject=subject,
            chapter=chapter,
            top_k=candidate_k,
            min_score=0.0,
        )
        vector_hits = self.vector.search(
            query,
            class_level=class_level,
            subject=subject,
            chapter=chapter,
            top_k=candidate_k,
            min_score=0.0,
        )
        # Grounding guard (R12): hashed-bucket collisions give a gibberish
        # query a small positive cosine against unrelated text, so a vector-
        # only candidate (found by NO lexical lane) must share Bangla
        # characters with the query to count as a phonetic-variant hit.
        bm_ids = {hit.chunk.id for hit in bm25_hits}
        query_bigrams = bengali_bigrams(query)
        vector_hits = [
            hit
            for hit in vector_hits
            if hit.chunk.id in bm_ids or query_bigrams & bengali_bigrams(vector_text(hit.chunk))
        ]

        by_id: dict[str, Chunk] = {}
        lexical_base: dict[str, float] = {}
        for hit in (*bm25_hits, *vector_hits):
            by_id.setdefault(hit.chunk.id, hit.chunk)
        for hit in bm25_hits:
            lexical_base[hit.chunk.id] = hit.score
        fused = reciprocal_rank_fusion(
            [[h.chunk.id for h in bm25_hits], [h.chunk.id for h in vector_hits]],
            k=self.rrf_k,
        )
        candidates = [
            (by_id[chunk_id], rrf_score, lexical_base.get(chunk_id, 0.0))
            for chunk_id, rrf_score in fused[:candidate_k]
        ]
        if not candidates:
            return []
        scores = self.reranker(query, candidates)
        ranked = [
            Hit(chunk=chunk, score=round(score, 4))
            for (chunk, _rrf, _base), score in zip(candidates, scores, strict=True)
            if score > min_score
        ]
        ranked.sort(key=lambda hit: (-hit.score, hit.chunk.id))
        return ranked[:top_k]


def iter_corpus_search(
    index: BM25Index | HybridIndex,
    queries: Iterable[str],
    **filters: object,
) -> list[list[Hit]]:
    """Batch helper for the hit@k evaluation harness (keeps top_k explicit)."""
    return [index.search(q, **filters) for q in queries]  # type: ignore[arg-type]
