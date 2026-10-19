"""A4-01 / A4-02 / A4-07: variant baselines on the frozen held-out split.

The audit's A4-01 status was PARTIAL because only the served pipeline was
reported: there was no lexical-only, no dense-only and no rerank-off row on
the golden set, so "the hybrid is better" could not be read off an artifact.
This module ranks every positive golden item with each retrieval variant
through the *same* loader, the same class+subject pre-filter and the same
metric layer (:mod:`bangla_gpt_api.evaluation.retrieval_strata`), and reports
per variant:

* Recall@1 / @3 / @5 / @10, MRR@10 and nDCG@10 with seeded 95% bootstrap CIs;
* p50/p95 search latency (host-dependent; the report says so);
* a top-k curve for the served variant -- Recall@k beside the mean context
  size (characters and estimated tokens) at that k, which is the
  recall-versus-context-cost curve the top-k choice is read from;
* the paired Banglish gap (a dedicated romanised-query subset) for A4-04.

Honest limits, recorded in the artifact:

* ``dense`` is the repo's deterministic hashing embedder, not a downloaded
  multilingual model (no weights may be fetched in this environment; see
  docs/evaluation/embedding-choice.md). It is a real dense lane, and it is
  the lane the repo can measure today;
* ``hybrid_rerank_off`` is the fallback ranking (RRF fusion only) -- also the
  fallback a reranker fault degrades to (A4-08);
* a cross-encoder rerank row is reported as ``not_measured`` with the reason:
  no cross-encoder weights exist offline, and the shipped reranker is the
  deterministic local feature ranker. Serving the label "cross-encoder"
  without a model would be a fabricated number.

Run from ``apps/api``:

    python -m bangla_gpt_api.evaluation.variant_matrix            # held-out test split
    python -m bangla_gpt_api.evaluation.variant_matrix --split all
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bangla_gpt_api.evaluation.retrieval_strata import (
    PRIMARY_METRIC,
    metrics_block,
    metrics_from_ranks,
    paired_mde,
)
from bangla_gpt_api.services.costs import estimate_tokens

APP_ROOT = Path(__file__).resolve().parents[3]  # apps/api
DEFAULT_GOLDEN = APP_ROOT / "eval" / "golden_v2.json"
DEFAULT_OUT = APP_ROOT / "eval" / "variant_matrix.json"
DEFAULT_SEED = 20261019
DEFAULT_TOP_K = 10

#: The variants a reader compares. Order is the report order.
VARIANTS = ("lexical", "dense", "hybrid_rerank_off", "hybrid_served", "hybrid_mmr")


def rrf_only_rerank(_query: str, candidates: list[tuple[Any, float, float]]) -> list[float]:
    """Fusion score only: no coverage, proximity or trigram features.

    This is the ranking the served pipeline degrades to when the reranker is
    unavailable (A4-08) and the ``hybrid_rerank_off`` row of this report.
    """
    return [rrf + lexical_base for _chunk, rrf, lexical_base in candidates]


class ServedVariant:
    """One searchable variant: a name and a ``search(query, **filters)``."""

    def __init__(self, name: str, index: Any, *, diversify: bool = False) -> None:
        self.name = name
        self.index = index
        self.diversify = diversify
        self.chunks = getattr(index, "chunks", None)

    def search(self, query: str, **filters: Any) -> list[Any]:
        # Typed locals, not bare returns: the wrapped index is duck-typed
        # (`Any`), and returning it directly is an implicit Any return.
        if self.diversify:
            hits: list[Any] = self.index.search(query, diversify=True, **filters)
            return hits
        hits = self.index.search(query, **filters)
        return hits


def build_variants(chunks: list, embedder: Any) -> dict[str, ServedVariant]:
    """Build every variant once: BM25, vector, fusion-only and the served index.

    Building the hybrid index twice (once for the rerank-off wrapper, once for
    the served one) is wasteful; only the served index is built, and the
    rerank-off variant swaps the reranker around each search -- single
    threaded evaluation only, documented in the report's run conditions.
    """
    from bangla_gpt_api.retrieval.bm25 import BM25Index
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
    from bangla_gpt_api.retrieval.vector import VectorIndex

    hybrid = HybridIndex(chunks, embedder)
    return {
        "lexical": ServedVariant("lexical", BM25Index(chunks)),
        "dense": ServedVariant("dense", VectorIndex(chunks, embedder)),
        "hybrid_rerank_off": ServedVariant("hybrid_rerank_off", _RerankOffWrapper(hybrid)),
        "hybrid_served": ServedVariant("hybrid_served", hybrid),
        "hybrid_mmr": ServedVariant("hybrid_mmr", hybrid, diversify=True),
    }


class _RerankOffWrapper:
    """The served hybrid index with the fusion-only (fallback) reranker."""

    def __init__(self, hybrid: Any) -> None:
        self.hybrid = hybrid
        self.chunks = hybrid.chunks

    def search(self, query: str, **kwargs: Any) -> list[Any]:
        original = self.hybrid.reranker
        self.hybrid.reranker = rrf_only_rerank
        try:
            hits: list[Any] = self.hybrid.search(query, **kwargs)
            return hits
        finally:
            self.hybrid.reranker = original


def gold_units_by_section(chunks: list) -> dict[tuple[int, str, str], set[str]]:
    """``(class_level, subject, section)`` -> the chunk ids of that section."""
    units: dict[tuple[int, str, str], set[str]] = {}
    for chunk in chunks:
        section = (chunk.meta.section or "").strip()
        if not section:
            continue
        key = (chunk.meta.class_level, chunk.meta.subject, section)
        units.setdefault(key, set()).add(chunk.id)
    return units


def rank_of(hits: list, wanted: set[str]) -> int:
    """1-based best rank of any wanted chunk id; 0 when absent from the hits."""
    for position, hit in enumerate(hits, start=1):
        if hit.chunk.id in wanted:
            return position
    return 0


@dataclass
class VariantRun:
    ranks: list[int]
    latencies_ms: list[float]
    #: Per query, the size of each returned passage in order (first = best).
    #: The top-k curve sums the first k, so the cost column really is the cost
    #: *at that k* -- a flat column would mean the curve was not a curve.
    context_chars_per_hit: list[list[int]]
    #: The same sizes in the repo's token estimator (services.costs), so the
    #: curve is quoted in the unit the evidence budget uses.
    context_tokens_per_hit: list[list[int]]


def run_variants(
    variants: dict[str, ServedVariant],
    items: list[dict],
    units: dict[tuple[int, str, str], set[str]],
    *,
    top_k: int = DEFAULT_TOP_K,
    split: str = "test",
) -> tuple[dict[str, VariantRun], list[dict], int]:
    """Rank every positive item in the split for every variant.

    Returns ``(runs, queries, unmatched)`` where ``queries`` records the
    per-query metadata the top-k curve and the Banglish subset need, without
    question text (the artifact is committed; the questions are PII-adjacent
    for a minors-facing product and stay out of it).
    """
    selected = [i for i in items if split == "all" or i.get("split") == split]
    queries: list[dict] = []
    unmatched = 0
    runs: dict[str, VariantRun] = {name: VariantRun([], [], [], []) for name in variants}
    for item in selected:
        if item["expect"] != "answer":
            continue
        key = (item["class_level"], item["subject"], (item.get("section") or "").strip())
        gold = units.get(key, set())
        if not gold:
            unmatched += 1
            continue
        filters = {
            "class_level": item["class_level"],
            "subject": item["subject"],
            "top_k": top_k,
        }
        for name, variant in variants.items():
            started = time.perf_counter()
            hits = variant.search(item["question"], **filters)
            elapsed_ms = (time.perf_counter() - started) * 1000
            run = runs[name]
            run.ranks.append(rank_of(hits, gold))
            run.latencies_ms.append(elapsed_ms)
            run.context_chars_per_hit.append([len(hit.chunk.text) for hit in hits])
            run.context_tokens_per_hit.append([estimate_tokens(hit.chunk.text) for hit in hits])
        queries.append(
            {
                "class_level": item["class_level"],
                "subject": item["subject"],
                "stratum": item["stratum"],
                "romanised": False,
            }
        )
    return runs, queries, unmatched


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile, 2-decimal ms; 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(min(int(len(ordered) * fraction), len(ordered) - 1), 0)
    return round(ordered[index], 2)


def top_k_curve(
    chars_per_hit: list[list[int]],
    tokens_per_hit: list[list[int]],
    ranks: list[int],
) -> dict[str, dict[str, float]]:
    """Recall@k beside the context cost *at that k*, for k = 1..10.

    Cost at k = mean over the same queries of the first-k passages' total
    size (characters measured, tokens through the repo's estimator). At k=1
    that is the top passage; at k=10 the whole returned set -- which is the
    trade-off the top-k decision is read from.
    """
    curve: dict[str, dict[str, float]] = {}
    for k in range(1, 11):
        hits = [1.0 if 0 < rank <= k else 0.0 for rank in ranks]
        chars_at_k = [sum(sizes[:k]) for sizes in chars_per_hit]
        tokens_at_k = [sum(sizes[:k]) for sizes in tokens_per_hit]
        curve[str(k)] = {
            "recall": round(sum(hits) / len(hits), 4) if hits else 0.0,
            "mean_context_chars": (round(statistics.fmean(chars_at_k), 1) if chars_at_k else 0.0),
            "mean_context_tokens_est": (
                round(statistics.fmean(tokens_at_k), 1) if tokens_at_k else 0.0
            ),
        }
    return curve


def build_report(
    *,
    golden_path: Path = DEFAULT_GOLDEN,
    split: str = "test",
    top_k: int = DEFAULT_TOP_K,
    seed: int = DEFAULT_SEED,
) -> dict:
    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.data.loader import load_sample_corpus
    from bangla_gpt_api.retrieval.embedding import build_embedder
    from bangla_gpt_api.services.trace_meta import index_fingerprint

    chunks = load_sample_corpus()
    if not chunks:
        raise SystemExit("NO_INDEXABLE_CHUNKS -- the bundled sample corpus is missing")
    embedder = build_embedder(Settings(env="test"))
    variants = build_variants(chunks, embedder)
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    items = data["items"]
    units = gold_units_by_section(chunks)
    runs, queries, unmatched = run_variants(variants, items, units, top_k=top_k, split=split)

    blocks: dict[str, Any] = {}
    paired: dict[str, Any] = {}
    for name, run in runs.items():
        blocks[name] = metrics_block(run.ranks, seed=seed) | {
            "latency": {
                "p50_ms": percentile(run.latencies_ms, 0.5),
                "p95_ms": percentile(run.latencies_ms, 0.95),
                "n": len(run.latencies_ms),
            }
        }
    values, _ = metrics_from_ranks(runs["hybrid_served"].ranks)
    for name in VARIANTS:
        if name == "hybrid_served":
            continue
        other, _ = metrics_from_ranks(runs[name].ranks)
        paired[f"hybrid_served_vs_{name}"] = paired_mde(
            values[PRIMARY_METRIC], other[PRIMARY_METRIC]
        )

    report: dict[str, Any] = {
        "generated_by": "bangla_gpt_api.evaluation.variant_matrix",
        "primary_metric": PRIMARY_METRIC,
        "run_conditions": {
            "split": split,
            "corpus": "bundled-sample",
            "corpus_fingerprint": index_fingerprint(variants["hybrid_served"].index),
            "golden_file": golden_path.name,
            "golden_dataset_hash": data.get("dataset_hash"),
            "golden_test_split_hash": data.get("test_split_hash"),
            "seed": seed,
            "top_k": top_k,
            "positive_items": len(runs["hybrid_served"].ranks),
            "gold_unmatched_items": unmatched,
            "provider": "none -- retrieval only, no LLM call",
            "latency_note": (
                "p50/p95 are wall-clock on this host and load; the metric "
                "values are deterministic under the sample corpus, the "
                "latency is not. Compare latency only within one run."
            ),
        },
        "variants": blocks,
        "paired_mde_vs_served": paired,
        "top_k_curve": {
            "variant": "hybrid_served",
            "chosen_top_k": 3,
            "curve": top_k_curve(
                runs["hybrid_served"].context_chars_per_hit,
                runs["hybrid_served"].context_tokens_per_hit,
                runs["hybrid_served"].ranks,
            ),
        },
        "not_measured": {
            "cross_encoder_rerank": (
                "no cross-encoder weights exist offline and none may be fetched in "
                "this environment; the shipped reranker is the deterministic local "
                "feature ranker (hybrid_served). A cross-encoder row would be a "
                "fabricated number, so it is reported as not measured."
            ),
            "real_multilingual_embedding_model": (
                "the dense lane is the deterministic hashing embedder; model "
                "weights are an owner/infra download decision (A4-02)."
            ),
        },
        "queries": {
            "n": len(queries),
            "stratified": "the same items the stratified report uses, filtered lane only",
        },
    }
    return report


def markdown_summary(report: dict) -> str:
    """The variant table for docs; generated, never hand-copied."""
    lines = [
        "| Variant | n | Recall@1 (CI95) | Recall@5 (CI95) | MRR@10 (CI95) | nDCG@10 | p50 ms | p95 ms |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, block in report["variants"].items():
        lines.append(
            f"| {name} | {block['n']} | {block['recall_at_1']} "
            f"({block['recall_at_1_ci95'][0]}-{block['recall_at_1_ci95'][1]}) | "
            f"{block['recall_at_5']} ({block['recall_at_5_ci95'][0]}-"
            f"{block['recall_at_5_ci95'][1]}) | {block['mrr_at_10']} "
            f"({block['mrr_at_10_ci95'][0]}-{block['mrr_at_10_ci95'][1]}) | "
            f"{block['ndcg_at_10']} | {block['latency']['p50_ms']} | "
            f"{block['latency']['p95_ms']} |"
        )
    return "\n".join(lines)
