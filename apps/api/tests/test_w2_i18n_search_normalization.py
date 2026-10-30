"""F-104: the same word must retrieve the same chunks however it is typed.

The corpus is ingested through the shared normalizer (NFKC plus zero-width
strip, ``retrieval/normalize.py``), and the tokenizer already folded queries
through it. The trigram lane did not: it grammed the raw query, so the same
word typed with a ZWNJ or a ZWJ (mobile IMEs and PDF copy-paste insert them)
or in the decomposed form of য় produced different trigram sets for the same
word -- different hits and different ranking at ``/search``.

These tests pin the retrieval contract the route relies on. The Bangla
literals are written directly; ``scripts/bn_scan.py`` keeps them NFC-clean.
"""

from __future__ import annotations

import unicodedata

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.retrieval.embedding import HashingEmbedder
from bangla_gpt_api.retrieval.hybrid import trigram_ngrams
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

ZWNJ = "\u200c"
ZWJ = "\u200d"

KOSH = "কোষ"  # cell
PRAYOG = "প্রয়োগ"  # application (composed য়)
# The decomposed spelling an editor or an old keyboard map can emit: য় is
# য + nukta, and the two-part vowel signs split as well.
PRAYOG_DECOMPOSED = unicodedata.normalize("NFD", PRAYOG)


def _chunk(chunk_id: str, section: str, text: str, chapter: str = "প্রাণিজগৎ") -> Chunk:
    return Chunk(
        id=chunk_id,
        text=text,
        meta=CurriculumMeta(
            curriculum_year=2012,
            class_level=6,
            subject="science",
            book="বিজ্ঞান",
            source="sample",
            chapter=chapter,
            section=section,
        ),
    )


def _corpus() -> list[Chunk]:
    return [
        _chunk("c1", f"{KOSH} কী", f"{KOSH} হলো জীবদেহের গঠন ও কাজের একক।"),
        _chunk("c2", f"{KOSH} বিভাজন", f"{KOSH} বিভাজন দুই প্রকার: মাইটোসিস ও মিয়োসিস।"),
        _chunk(
            "c3",
            "বল",
            f"{PRAYOG}ে বস্তুর গতি বদলায়।",
            chapter="বল ও শক্তি",
        ),
    ]


def _hits(index: BM25Index | HybridIndex, query: str) -> list[tuple[str, float]]:
    return [(hit.chunk.id, hit.score) for hit in index.search(query, top_k=10)]


def test_trigram_ngrams_fold_zero_width_and_yya_forms() -> None:
    """The trigram set is a property of the word, not of its typed encoding."""
    plain = trigram_ngrams(KOSH)
    assert trigram_ngrams(KOSH[:2] + ZWNJ + KOSH[2:]) == plain
    assert trigram_ngrams(KOSH[:2] + ZWJ + KOSH[2:]) == plain
    # Index-side strings are stored normalized; gramming them again is
    # idempotent, which is what makes query-side normalization safe here.
    assert trigram_ngrams(unicodedata.normalize("NFC", KOSH)) == plain

    composed = trigram_ngrams(PRAYOG)
    assert composed == trigram_ngrams(PRAYOG_DECOMPOSED)
    assert composed == trigram_ngrams(unicodedata.normalize("NFC", PRAYOG_DECOMPOSED))


def test_bm25_search_same_hits_for_zero_width_variants() -> None:
    index = BM25Index(_corpus())
    baseline = _hits(index, KOSH)
    assert baseline, "the fixture corpus must match the plain spelling"

    assert _hits(index, KOSH[:2] + ZWNJ + KOSH[2:]) == baseline
    assert _hits(index, KOSH[:2] + ZWJ + KOSH[2:]) == baseline


def test_bm25_search_same_hits_for_decomposed_yya() -> None:
    index = BM25Index(_corpus())
    baseline = _hits(index, PRAYOG)
    assert baseline, "the fixture corpus must match the composed spelling"

    assert _hits(index, PRAYOG_DECOMPOSED) == baseline


def test_hybrid_search_same_hits_for_zero_width_variants() -> None:
    index = HybridIndex(_corpus(), HashingEmbedder())
    baseline = _hits(index, KOSH)
    assert baseline

    assert _hits(index, KOSH[:2] + ZWNJ + KOSH[2:]) == baseline
    assert _hits(index, KOSH[:2] + ZWJ + KOSH[2:]) == baseline
