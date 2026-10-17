"""RAG v2 -- hybrid retrieval index: BM25 + vector -> RRF -> rerank.

Pipeline (master spec 4.3): section chunking (TextIngester, chunk.meta.
section) -> embedder (retrieval/embedding.py) -> vector lane
(retrieval/vector.py) + lexical lane (BM25Index) -> reciprocal rank fusion
(retrieval/fusion.py) -> reranker -> top_k.

``search`` is signature-compatible with:meth:`BM25Index.search`, so the
hybrid index is a drop-in for TutorService/the generation retrievers.
The reranker is a deterministic feature ranker (:func:`make_lexical_rerank`
documents the feature set and why each weight is what it is); a model-based
reranker replaces exactly one stage of this pipeline when one is benchmarked.
"""

from collections.abc import Callable, Iterable

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.retrieval.bm25 import BM25Index, Hit, indexable_text, tokenize
from bangla_gpt_api.retrieval.embedding import Embedder, bengali_bigrams
from bangla_gpt_api.retrieval.fusion import reciprocal_rank_fusion
from bangla_gpt_api.retrieval.hybrid import light_stem, trigram_similarity
from bangla_gpt_api.retrieval.query_analysis import (
    content_terms,
    coverage_weights,
    weighted_coverage,
)
from bangla_gpt_api.retrieval.vector import VectorIndex, vector_text
from bangla_gpt_api.retrieval.vocabulary import TermStats

#: rerank(query, [(chunk, rrf_score, lexical_lane_base_score)]) -> final scores
Reranker = Callable[[str, list[tuple[Chunk, float, float]]], list[float]]

_RRF_K = 60
#: candidate pool per lane before fusion (RRF then trims)
_CANDIDATE_FACTOR = 3

# Final-score blend. Fusion agreement is the base; the query re-check rewards
# the candidate that actually answers the question. The proximity weight is
# what turns Recall@5 into Recall@1 on the measured traffic: the right chunk
# was already in the candidate set (self-sentence Recall@5 1.00 vs Recall@1
# 0.38 on the real corpus), and the competing chunks are the same chapter's
# *other* sections, whose matched query terms sit scattered across the whole
# body. The chunk where the matched terms cluster inside one definition
# sentence is the section the query names.
_W_RRF = 1.0
_W_COVERAGE = 0.5
_W_PROXIMITY = 0.8
_W_TRIGRAM = 0.3

#: tokens within which matched content terms must sit to count as one
#: explanation. Sample-corpus definition sentences run 12-40 tokens.
_PROXIMITY_WINDOW = 40


def _minimal_window(positions: list[list[int]]) -> int:
    """Smallest token span (inclusive) holding one position of every term.

    Two-pointer sweep over the merged, sorted positions. A single matched
    term has a span of 1.
    """
    flat = sorted((pos, which) for which, plist in enumerate(positions) for pos in plist)
    need = len(positions)
    counts: dict[int, int] = {}
    have = 0
    best = 10**9
    left = 0
    for right, (_pos, which) in enumerate(flat):
        counts[which] = counts.get(which, 0) + 1
        if counts[which] == 1:
            have += 1
        while have == need:
            best = min(best, flat[right][0] - flat[left][0] + 1)
            left_which = flat[left][1]
            counts[left_which] -= 1
            if counts[left_which] == 0:
                have -= 1
            left += 1
    return best if best < 10**9 else 10**9


def make_lexical_rerank(term_stats: TermStats | None = None) -> Reranker:
    """Build the deterministic reranker, frequency-aware when the corpus says so.

    Features per candidate, computed over the text the lexical lane indexes
    (section heading + chapter + body — :func:`indexable_text`):

    ``weighted_coverage``
      Fraction of the question's *content* terms (stop-words — copulas,
      conjunctions, question particles — excluded) present in the candidate,
      weighted by corpus document frequency. A missed ubiquitous term ("এবং")
      barely moves the score; a missed one-of-a-kind curriculum term
      ("সালোকসংশ্লেষণ") dominates it. Without statistics every content term
      weighs 1, and the score degrades to plain coverage.
    ``proximity``
      How tightly the matched terms cluster:
      ``covered_terms / minimal_token_window``. A candidate whose matches sit
      30 tokens apart is talking about two different things; matches inside
      one sentence are the definition the query asked for.
    ``trigram``
      Character-trigram similarity, retained for the phonetic-variant tail
      ("কোশ" against "কোষ") and the Banglish lane.

    The lexical-lane base score stays the magnitude base so hybrid scores
    remain on the BM25 scale (callers gate on it). A chunk found by no
    lexical lane keeps a small fusion-only score: enough for the tutor's
    grounded flow, too small to fake evidence a lexical search did not find.
    """

    def weight_map(terms: tuple[str, ...]) -> dict[str, float]:
        if term_stats is None:
            return {t: 1.0 for t in terms}
        return coverage_weights(
            terms,
            {t: term_stats.document_frequency(t) for t in terms},
            term_stats.total_documents,
        )

    def rerank(query: str, candidates: list[tuple[Chunk, float, float]]) -> list[float]:
        query_terms = content_terms(query)
        if not query_terms:
            # a question made only of function words still has to gate
            query_terms = tuple(
                dict.fromkeys(light_stem(t) for t in tokenize(query) if len(t) >= 2)
            )
        weights = weight_map(query_terms)
        scores: list[float] = []
        for chunk, rrf_score, lexical_base in candidates:
            text_tokens = tokenize(indexable_text(chunk))
            chunk_terms = {light_stem(t) for t in text_tokens}
            covered = [t for t in query_terms if t in chunk_terms]
            weighted = weighted_coverage(query_terms, covered, weights) if query_terms else 0.0
            positions = [
                [i for i, tok in enumerate(text_tokens) if light_stem(tok) == term]
                for term in covered
            ]
            proximity = len(covered) / max(_minimal_window(positions), 1) if covered else 0.0
            tri = trigram_similarity(query, indexable_text(chunk))
            scores.append(
                lexical_base
                + _W_RRF * rrf_score
                + _W_COVERAGE * weighted
                + _W_PROXIMITY * min(proximity, 1.0)
                + _W_TRIGRAM * tri
            )
        return scores

    return rerank


def lexical_rerank(query: str, candidates: list[tuple[Chunk, float, float]]) -> list[float]:
    """Deterministic rerank without corpus statistics.

    The module-level default so direct callers (tests, ``/search``) keep the
    original contract: coverage is uniform-weighted over all query tokens and
    no proximity is scored. The production index builds its reranker through
    :func:`make_lexical_rerank` with corpus statistics.
    """
    query_terms = {light_stem(t) for t in tokenize(query) if len(t) >= 2}
    scores: list[float] = []
    for chunk, rrf_score, lexical_base in candidates:
        if query_terms:
            chunk_terms = {light_stem(t) for t in tokenize(indexable_text(chunk))}
            coverage = sum(1 for t in query_terms if t in chunk_terms) / len(query_terms)
        else:
            coverage = 0.0
        tri = trigram_similarity(query, indexable_text(chunk))
        scores.append(lexical_base + _W_RRF * rrf_score + _W_COVERAGE * coverage + _W_TRIGRAM * tri)
    return scores


class HybridIndex:
    """BM25 + vector lanes fused by RRF, then reranked. BM25-shaped API."""

    def __init__(
        self,
        chunks: list[Chunk],
        embedder: Embedder,
        *,
        reranker: Reranker | None = None,
        rrf_k: int = _RRF_K,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.chunks = chunks
        self.bm25 = BM25Index(chunks, k1=k1, b=b)
        self.vector = VectorIndex(chunks, embedder)
        self.rrf_k = rrf_k
        # The default reranker is the corpus-aware one: statistics come from
        # this index's own lexical lane, so reranking, the grounding gate and
        # the query expansion all read the same document frequencies. An
        # explicit reranker still wins (tests, experiments).
        self.reranker: Reranker = reranker or make_lexical_rerank(self.bm25.term_stats)

    @property
    def term_stats(self) -> TermStats:
        """Corpus term statistics of the lexical lane (for the grounding gate)."""
        return self.bm25.term_stats

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
        # Grounding guard: hashed-bucket collisions give a gibberish
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
