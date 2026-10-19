"""Retrieval-time diversity (MMR) for near-duplicate candidates (AUD-A1-10).

The corpus carries near-duplicate passages (shared front-matter pages,
reprinted editions); the fusion + rerank stack happily returns two thirds of
the context window from the same repeated passage. Maximal Marginal
Relevance is the standard cheap fix: greedily pick the candidate that
maximises ``relevance - λ · max_similarity(already selected)`` with token-set
Jaccard as the similarity (deterministic, dependency-free, same tokenizer as
the lexical lane).

Not a default: the ablation (``scripts/ablate_nctb_chunking.py``) measures
it on the real corpus and the result is recorded in
``docs/RAG_ARCHITECTURE.md``. Callers opt in with ``diversify=True`` (or by
passing a different λ) and keep the pre-diversity behaviour otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable

from bangla_gpt_api.retrieval.bm25 import Hit, indexable_text, tokenize

#: Relevance-vs-redundancy trade-off. 1.0 = pure relevance (no-op), 0.0 =
#: pure diversity. 0.7 keeps the top hit first in every measured family
#: while displacing near-identical repeats.
DEFAULT_LAMBDA = 0.7


def _token_set(text: str) -> frozenset[str]:
    return frozenset(tokenize(text))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def mmr_select(
    hits: Iterable[Hit],
    *,
    k: int,
    lambda_: float = DEFAULT_LAMBDA,
) -> list[Hit]:
    """Re-rank ``hits`` by MMR and keep ``k``; order-stable on ties.

    Similarity is measured over the same text the lexical lane indexes
    (heading included), so two chunks that only differ in their heading are
    still recognised as near-duplicates.
    """
    candidates = list(hits)
    if k <= 0 or len(candidates) <= 1 or lambda_ >= 1.0:
        return candidates[:k] if k > 0 else []
    token_sets = {hit.chunk.id: _token_set(indexable_text(hit.chunk)) for hit in candidates}
    chosen: list[Hit] = []
    remaining = list(candidates)
    while remaining and len(chosen) < k:
        best_index = 0
        best_score = float("-inf")
        for index, hit in enumerate(remaining):
            if not chosen:
                redundancy = 0.0
            else:
                redundancy = max(
                    _jaccard(token_sets[hit.chunk.id], token_sets[other.chunk.id])
                    for other in chosen
                )
            score = lambda_ * hit.score - (1 - lambda_) * redundancy
            if score > best_score:
                best_score = score
                best_index = index
        chosen.append(remaining.pop(best_index))
    return chosen
