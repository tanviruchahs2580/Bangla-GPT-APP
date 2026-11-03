"""BM25 inverted-postings equivalence (RAG audit F-02/C1).

The postings fold must be an OPTIMIZATION ONLY: every query that the legacy
whole-corpus scan answered must be answered with the identical Hit list —
same scores, same order, same tie-breaks. This file pins that by running a
reference implementation of the legacy scan (verbatim arithmetic, legacy
term order, legacy soft-trigram combination) next to the real index over
the bundled corpus, across the query shapes the app actually serves:
in-corpus Bangla, Banglish, English gloss targets, numerals, gibberish,
with and without class/subject filters, at different top_k.
"""

from __future__ import annotations

from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.retrieval.bm25 import (
    _TRIGRAM_WEIGHT,
    BM25Index,
    Hit,
    expand_query,
    light_stem,
    tokenize,
)
from bangla_gpt_api.retrieval.hybrid import trigram_jaccard, trigram_ngrams

QUERIES: list[tuple[str, dict[str, object]]] = [
    ("কোষ কী", {}),
    ("ভগ্নাংশ কী এবং কেন ব্যবহার হয়", {}),
    ("kosh ki", {}),
    ("cell কী", {}),
    ("zzqq blorg wumpus", {}),
    ("সালোকসংশ্লেষণ উদ্ভিদের কোথায় ঘটে", {}),
    ("৭ সংখ্যা কীসের", {"class_level": 7}),
    ("আলোর প্রতিফলন", {"class_level": 6, "subject": "science"}),
    ("trikonmiti ki", {"class_level": 9}),
    ("photosynthesis", {"subject": "science"}),
]


def _reference_search(
    index: BM25Index,
    query: str,
    *,
    class_level: int | None = None,
    subject: str | None = None,
    chapter: str | None = None,
    top_k: int = 4,
    min_score: float = 0.0,
) -> list[Hit]:
    """Verbatim legacy whole-corpus scan (pre-postings)."""
    raw_terms = tokenize(query)
    query_terms = expand_query(
        [light_stem(t) for t in raw_terms],
        extra=index._query_side_expansions(raw_terms),
    )
    query_grams = trigram_ngrams(query)
    hits: list[Hit] = []
    for i, chunk in enumerate(index.chunks):
        if class_level is not None and chunk.meta.class_level != class_level:
            continue
        if subject is not None and chunk.meta.subject != subject:
            continue
        if chapter is not None and chunk.meta.chapter != chapter:
            continue
        score = index._score(query_terms, i)
        jaccard = trigram_jaccard(query_grams, index._trigrams[i])
        if score <= min_score:
            soft = _TRIGRAM_WEIGHT * jaccard
            if soft > score:
                score = soft
        else:
            score += 0.3 * _TRIGRAM_WEIGHT * jaccard
        if score > 0:
            hits.append(Hit(chunk=chunk, score=round(score, 4)))
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:top_k]


def test_postings_scan_is_bit_identical_to_the_legacy_scan() -> None:
    index = BM25Index(load_sample_corpus())
    for query, filters in QUERIES:
        legacy = _reference_search(index, query, **filters)  # type: ignore[arg-type]
        served = index.search(query, **filters)  # type: ignore[arg-type]
        assert [(h.chunk.id, h.score) for h in served] == [(h.chunk.id, h.score) for h in legacy], (
            f"postings fold changed retrieval for {query!r} {filters}"
        )


def test_postings_cover_every_indexed_term() -> None:
    index = BM25Index(load_sample_corpus())
    for doc, tf in enumerate(index.term_freqs):
        for term, count in tf.items():
            assert (doc, count) in index._postings[term]
