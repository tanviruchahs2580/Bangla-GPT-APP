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


def test_term_stats_surface_is_the_index_vocabulary() -> None:
    index = BM25Index(load_sample_corpus())
    assert index.term_stats is index.vocabulary


def test_postings_cover_every_indexed_term() -> None:
    index = BM25Index(load_sample_corpus())
    for doc, tf in enumerate(index.term_freqs):
        for term, count in tf.items():
            assert (doc, count) in index._postings[term]


def test_postings_scan_honours_min_score_lanes() -> None:
    # Pins the two score-combination arcs the postings fold added: the
    # soft-replacement lane (score <= min_score) and the additive lane
    # (score > min_score) must both behave exactly like the legacy scan.
    index = BM25Index(load_sample_corpus())
    strong = index.search("কোষ কী", class_level=6, min_score=2.0)
    legacy_strong = _reference_search(index, "কোষ কী", class_level=6, min_score=2.0)
    assert [(h.chunk.id, h.score) for h in strong] == [(h.chunk.id, h.score) for h in legacy_strong]
    gibberish = index.search("zzqq blorg", class_level=6)
    legacy_gibberish = _reference_search(index, "zzqq blorg", class_level=6)
    assert [(h.chunk.id, h.score) for h in gibberish] == [
        (h.chunk.id, h.score) for h in legacy_gibberish
    ]


def test_postings_additive_lane_and_soft_false_arc() -> None:
    # additive lane (bm25 > min_score → the 0.3 blend) and the
    # soft>score-FALSE arc inside the replace lane: together with the
    # equivalence pairs above these are the only uncovered arcs the
    # postings rewrite added.
    index = BM25Index(load_sample_corpus())
    rich = "কোষ কী কোষের প্রধান অংশ কোষ কী"
    hits = index.search(rich, class_level=6, min_score=2.0)
    legacy = _reference_search(index, rich, class_level=6, min_score=2.0)
    assert [(h.chunk.id, h.score) for h in hits] == [(h.chunk.id, h.score) for h in legacy]
    assert any(h.score > 2.0 for h in hits), "the additive lane must run on a rich query"

    # soft>score FALSE: a gibberish query whose shared-trigram jaccard is
    # nonzero but too small to beat the zero BM25 score
    partial = "কোষ্টীজীবনযাপনব্যবস্থা"
    a = index.search(partial, class_level=6)
    b = _reference_search(index, partial, class_level=6)
    assert [(h.chunk.id, h.score) for h in a] == [(h.chunk.id, h.score) for h in b]


def test_postings_multi_doc_additive_and_filter_arcs() -> None:
    index = BM25Index(load_sample_corpus())
    # several docs clear a low floor -> the additive else-body loops back to
    # the scan head (the 167->152 arc), while weak docs take the soft lane
    hits = index.search("কোষ কী কোষের প্রধান অংশ কোষ কী", class_level=6, min_score=1.0)
    legacy = _reference_search(index, "কোষ কী কোষের প্রধান অংশ কোষ কী", class_level=6, min_score=1.0)
    assert [(h.chunk.id, h.score) for h in hits] == [(h.chunk.id, h.score) for h in legacy]
    assert sum(1 for h in hits if h.score > 1.0) >= 2

    # an English stop-word rides the ascii lane and is dropped before the
    # vocabulary gates (the pre-expansion continue arc)
    stopped = "and কোষ"
    assert [(h.chunk.id, h.score) for h in index.search(stopped, class_level=6)] == [
        (h.chunk.id, h.score) for h in _reference_search(index, stopped, class_level=6)
    ]


def _synthetic_corpus():
    from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
    from bangla_gpt_api.retrieval.bm25 import indexable_text  # noqa: F401

    def meta(chapter):
        return CurriculumMeta(
            curriculum_year=2023,
            class_level=6,
            subject="science",
            book="b",
            source="syn",
            chapter=chapter,
        )

    return [
        Chunk(id="s1", text="কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত একক এবং কার্যগত একক", meta=meta("কোষ")),
        Chunk(id="s2", text="sin cos tan and x 42", meta=meta("সূচক")),
        Chunk(id="s3", text="পদার্থবিজ্ঞানের মৌলিক ধারণা প্রয়োগ", meta=meta("পদার্থ")),
    ]


def test_postings_chapter_filter_zero_share_and_vocab_arcs() -> None:
    index = BM25Index(_synthetic_corpus())
    # chapter filter: docs outside the chapter take the continue arc
    assert index.search("কোষ", chapter="কোষ"), "in-chapter probe keeps a hit"
    assert index.search("কোষ", chapter="পদার্থ") == [], "outside-chapter docs take the continue arc"  # noqa: E501 - arc identifier inline
    # postings-only Latin doc with zero shared trigrams: soft>score is FALSE
    index.search("x কোষ")  # arc 163→167 (soft<=score), then the score>0 gate
    # an ascii token already sitting in the corpus vocabulary takes BOTH the
    # seen-continue arc and the not-seen gloss/roman fall-through arc
    index.search("sin কোষ")

    # postings-only Latin doc with ZERO shared trigrams: the soft lane stays
    # empty so `soft > score` is FALSE (arc 163→167) and the scan continues
    # to the next candidate afterwards (arc 167→152)
    floor_hits = index.search("x কোষ", min_score=2)
    legacy_floor = _reference_search(index, "x কোষ", min_score=2)
    assert [(h.chunk.id, h.score) for h in floor_hits] == [
        (h.chunk.id, h.score) for h in legacy_floor
    ]
