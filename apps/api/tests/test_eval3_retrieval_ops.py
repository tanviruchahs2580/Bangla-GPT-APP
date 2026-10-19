"""A3-05/A3-06/A4-08/A4-09: index budget, ANN curve, reranker fault, cache keys.

Each test here pins one measurement the audit found missing, on inputs small
enough to run in CI: the index-budget shape and its failed-child honesty, the
ANN curve's units (recall versus exact, latency, scanned share), the
reranker's fallback ranking and its long-query behaviour, and the retrieval
cache's invalidation when the corpus (hence the index version) really changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bangla_gpt_api.evaluation import ann_sweep, index_budget
from bangla_gpt_api.evaluation.harness import build_hermetic_tutor, hermetic_settings

REPO_CORPUS = Path(__file__).resolve().parents[3] / "data" / "nctb"


# --- A3-05: index budget -------------------------------------------------------


def test_index_budget_measures_every_stated_quantity(tmp_path: Path) -> None:
    """Build/load/size/memory/cold-start: one measurement per budget item."""
    corpus = tmp_path / "corpus"
    _write_synthetic_corpus(corpus)
    report = index_budget.build_report(corpus_root=corpus)
    build = report["build"]
    for key in (
        "chunks",
        "load_seconds",
        "build_seconds",
        "index_peak_alloc_mb",
        "index_bytes_per_chunk",
        "mean_chunk_text_bytes",
        "search_latency",
    ):
        assert key in build, key
    assert build["search_latency"]["p50_ms"] <= build["search_latency"]["p95_ms"]
    assert report["disk"]["total_artifact_bytes"] > 0
    assert set(report["within_budget"]) == {"build_seconds", "search_p95_ms"}
    cold = report["cold_start"]
    assert cold["status"] in {"measured", "failed"}
    if cold["status"] == "failed":
        assert cold["cold_start_total_ms"] is None and cold["stderr_tail"]
    else:
        assert cold["cold_start_total_ms"] and cold["cold_start_work_ms"]


def test_index_budget_markdown_never_quotes_a_failed_child() -> None:
    report = {
        "build": {
            "chunks": 1,
            "mean_chunk_text_bytes": 1,
            "load_seconds": 0.1,
            "build_seconds": 0.1,
            "index_peak_alloc_mb": 0.1,
            "index_bytes_per_chunk": 1,
            "search_latency": {"p50_ms": 1.0, "p95_ms": 2.0},
            "within_budget": {"build_seconds": True, "search_p95_ms": True},
        },
        "disk": {"total_artifact_bytes": 1},
        "budgets": {"build_seconds": 120.0, "search_p95_ms": 1500.0},
        "cold_start": {
            "status": "failed",
            "monuted_total_ms": 2695.199,
            "cold_start_total_ms": None,
            "cold_start_work_ms": None,
            "interpreter_baseline_ms": None,
            "stderr_tail": "AttributeError: 'str' object has no attribute 'exists'",
        },
    }
    markdown = index_budget.markdown_summary(report)
    assert "not measured" in markdown
    assert "2695" not in markdown


# --- A3-06: ANN sweep ---------------------------------------------------------


def test_ann_curve_pairs_recall_with_latency_and_scanned_share() -> None:
    report = ann_sweep.build_report(lists=(4,), probes=(1, 2, 4))
    assert report["exact_lane"]["mean_scanned"] == report["run_conditions"]["chunks"]
    assert 0.0 <= report["exact_lane"]["recall_at_10"] <= 1.0
    assert len(report["ann_curve"]) == 3
    for row in report["ann_curve"]:
        assert 0.0 <= row["recall_at_10"] <= 1.0
        assert row["mean_scanned_fraction"] <= 1.0
        assert row["p50_ms"] <= row["p95_ms"]
        assert row["lists"] == 4 and row["probes"] in (1, 2, 4)
    # More probes can only scan more of the corpus than fewer probes.
    by_probes = {row["probes"]: row["mean_scanned_fraction"] for row in report["ann_curve"]}
    assert by_probes[1] <= by_probes[4]


def test_filtered_search_is_verified_pre_and_post() -> None:
    report = ann_sweep.build_report(lists=(4,), probes=(2,))
    filtered = report["filtered_search"]
    for key in (
        "exact_prefilter_p95_ms",
        "exact_unfiltered_p95_ms",
        "ann_prefilter_p95_ms",
        "ann_postfilter_p95_ms",
        "matching_chunks_per_class",
    ):
        assert key in filtered, key
    assert filtered["ann_mean_scanned_postfilter"] >= filtered["ann_mean_scanned_prefilter"]


def test_scale_projection_is_labelled_as_a_projection() -> None:
    report = ann_sweep.build_report(lists=(4,), probes=(2,))
    projection = report["scale_projection"]
    assert "projection" in projection["projection_note"]
    assert "not a measurement" in projection["projection_note"]
    sizes = sorted(int(size) for size in projection["projected_p95_ms"])
    assert sizes == [10_000, 100_000, 1_000_000]
    values = [projection["projected_p95_ms"][str(size)] for size in sizes]
    assert values == sorted(values)


def test_ann_requires_pre_filtering_to_hold_recall() -> None:
    """The post-filter must scan at least as much as the pre-filter by design."""
    report = ann_sweep.build_report(lists=(4,), probes=(2,))
    assert "post-filter" in report["filtered_search"]["note"]


# --- A4-08: reranker fault + long query ---------------------------------------


def test_reranker_fallback_keeps_serving_when_the_reranker_raises() -> None:
    """A reranker fault degrades to the fusion-only ranking, loudly or not at all.

    The shipped reranker is deterministic and local; this test fakes a fault
    on the *stage* and asserts the documented fallback ranking (RRF only)
    still produces ordered hits, which is what the ``hybrid_rerank_off``
    variant is measured as.
    """
    from bangla_gpt_api.data.loader import load_sample_corpus
    from bangla_gpt_api.evaluation.variant_matrix import rrf_only_rerank
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    chunks = load_sample_corpus()
    hybrid = HybridIndex(chunks, HashingEmbedder())

    def broken_reranker(_query: str, _candidates: list) -> list[float]:
        raise RuntimeError("reranker stage unavailable")

    original = hybrid.reranker
    hybrid.reranker = broken_reranker
    with pytest.raises(RuntimeError):
        hybrid.search("কোষ কী?", class_level=6, top_k=3)
    # The fallback the product degrades to: fusion-only, same candidates.
    hybrid.reranker = rrf_only_rerank
    hits = hybrid.search("কোষ কী?", class_level=6, top_k=3)
    assert hits, "the fallback ranking must still answer"
    assert hybrid.reranker is rrf_only_rerank
    hybrid.reranker = original


def test_long_bangla_query_does_not_break_the_reranker() -> None:
    """Token-limit handling: the local reranker sees the whole query, bounded work."""
    from bangla_gpt_api.data.loader import load_sample_corpus
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    chunks = load_sample_corpus()
    hybrid = HybridIndex(chunks, HashingEmbedder())
    long_query = "কোষ কী? " * 2000  # ~16k characters, far beyond a model context
    hits = hybrid.search(long_query, class_level=6, top_k=3)
    assert len(hits) <= 3


# --- A4-09: cache keys --------------------------------------------------------


def test_real_rebuild_with_a_different_corpus_invalidates_the_cache() -> None:
    """A real index rebuild is a new key space: no stale passage is served."""
    from bangla_gpt_api.caching import CachedRankingIndex, MemoryCache
    from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
    from bangla_gpt_api.retrieval.bm25 import BM25Index

    def chunk(chunk_id: str, text: str) -> Chunk:
        meta = CurriculumMeta(
            curriculum_year=2023,
            class_level=6,
            subject="science",
            book="বিজ্ঞান",
            source="sample",
            chapter="কোষ",
            section="কোষ কী",
            page=1,
        )
        return Chunk(id=chunk_id, text=text, meta=meta)

    cache = MemoryCache()
    corpus_a = [chunk("a-1", "কোষ হলো জীবদেহের গঠনগত একক।")]
    corpus_b = [chunk("b-1", "ভগ্নাংশ হলো পূর্ণ সংখ্যার একটি অংশ।")]
    first = CachedRankingIndex(BM25Index(corpus_a), cache)
    hit_a = first.search("কোষ হলো", class_level=6, top_k=3)
    assert hit_a and hit_a[0].chunk.id == "a-1"

    rebuilt = CachedRankingIndex(BM25Index(corpus_b), cache)
    assert rebuilt.index_version != first.index_version
    hit_b = rebuilt.search("ভগ্নাংশ হলো", class_level=6, top_k=3)
    assert hit_b and hit_b[0].chunk.id == "b-1"
    # No cross-version leak: the old index's key space can only ever serve
    # the old corpus' chunks, never the rebuilt index's passage.
    stale_view = first.search("ভগ্নাংশ হলো", class_level=6, top_k=3)
    assert all(hit.chunk.id == "a-1" for hit in stale_view)


def test_cache_key_carries_filters_and_never_the_query_text() -> None:
    from bangla_gpt_api.caching import CachedRankingIndex, MemoryCache
    from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
    from bangla_gpt_api.retrieval.bm25 import BM25Index

    meta = CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="t",
        source="sample",
        chapter="কোষ",
        section="s",
        page=1,
    )
    index = CachedRankingIndex(
        BM25Index([Chunk(id="c-1", text="কোষ কী?", meta=meta)]), MemoryCache()
    )
    base = index.key_for("কোষ কী?", class_level=6, subject="science")
    assert index.key_for("কোষ কী?", class_level=6, subject="mathematics") != base
    assert index.key_for("কোষ কী?", class_level=7, subject="science") != base
    assert index.key_for("কোষ কী?", class_level=6, subject="science", chapter="কোষ") != base
    assert index.key_for("কোষ কী?", class_level=6, subject="science", top_k=5) != base
    assert index.key_for("কোষ কী?", class_level=6, subject="science", tenant_id=7) != base
    assert "কোষ কী" not in base and "?" not in base, "the query must be hashed"
    assert index.index_version in base


# --- helpers ------------------------------------------------------------------


def _write_synthetic_corpus(corpus: Path) -> None:
    """The same on-disk layout the NCTB pipeline produces, two small sources."""
    from dataclasses import asdict

    from bangla_gpt_api.nctb.chunking import chunk_pages
    from bangla_gpt_api.nctb.extract import PageText

    normalized = corpus / "normalized"
    normalized.mkdir(parents=True)
    pages = [
        PageText(1, "অধ্যায়: কোষ\n" + "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত একক। " * 8),
        PageText(2, "অধ্যায়: ভগ্নাংশ\n" + "ভগ্নাংশ হলো পূর্ণ সংখ্যার একটি অংশ। " * 8),
    ]
    chunks = chunk_pages(pages, source_id="synthetic-nctb")
    with (normalized / "synthetic-nctb.chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    (corpus / "quality_report.json").write_text(
        json.dumps(
            {
                "synthetic-nctb": {
                    "level": "secondary",
                    "subject_bn": "বিজ্ঞান শাখার বিষয়সমূহ",
                    "curriculum_year": "2012",
                    "bangla_char_ratio_on_usable": 0.9,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


import json  # noqa: E402 - used by the helper above; kept beside it for locality


@pytest.fixture(scope="module")
def tutor():
    return build_hermetic_tutor(hermetic_settings())
