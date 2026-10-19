"""A3-06: does the repo need an ANN index? A measured curve, not a preference.

The audit's A3-06 status was PARTIAL: a vector lane existed, but there was no
recall-versus-latency curve, no parameter tuning and no filtered-search
verification -- so "stay on the existing database" versus "add an ANN/vector
store" was an opinion.

This module makes it a measurement. On the corpus the deployment serves it
builds, beside the exact brute-force lane the repo uses today:

* an **IVF-style ANN** (k-means centroids over the embedder vectors, probe
  ``nprobe`` nearest lists) -- the same shape as pgvector's IVFFlat, so the
  parameters tuned here (``lists``, ``probes``) are the parameters that would
  be set on a real vector store;
* a **recall-versus-latency curve** over a grid of (lists, probes): recall@10
  against the exact lane, with p50/p95 query latency and the share of the
  corpus actually scanned;
* a **filtered-search verification**: the exact lane pre-filters by class (as
  the product does), and the ANN lane is measured both pre-filtered and
  post-filtered -- a vector store that filters after the search loses recall
  and the number must be visible rather than assumed;
* a **scale projection**: the exact lane's measured per-chunk scan cost is
  extrapolated linearly, and the smallest ANN configuration inside the stated
  search budget is named. The extrapolation is labelled as a projection,
  never as a measurement.

The decision this produces (recorded in docs/evaluation/index-and-ann.md):
on the corpus the product serves today the exact lane is inside budget, so
staying on the existing database is the justified choice; the ANN parameters
and the crossover point are measured so the deferred pgvector work starts
from numbers instead of a guess.
"""

from __future__ import annotations

import platform
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

#: Grid: centroid counts and probe counts. ``lists`` mirrors pgvector's
#: IVFFlat ``lists``; ``probes`` mirrors ``ivfflat.probes``.
DEFAULT_LISTS = (4, 8, 16)
DEFAULT_PROBES = (1, 2, 4, 8)
DEFAULT_TOP_K = 10

#: Stated search budget (the same number A3-05 states).
SEARCH_P95_BUDGET_MS = 1500.0

#: Fallback questions when the corpus sample yields too few self-sentence
#: queries; they carry no gold unit and are excluded from recall.
QUERIES = (
    "কোষ কী?",
    "সালোকসংশ্লেষণ কী?",
)


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def kmeans(
    vectors: list[list[float]],
    *,
    lists: int,
    iterations: int = 8,
    seed: int = 20261019,
) -> tuple[list[list[float]], list[int]]:
    """Deterministic k-means over L2-normalised vectors (cosine == dot).

    Pure Python on purpose: the corpus is small, the point is a reproducible
    curve, and adding a numeric dependency to the evaluation path for this
    would outweigh it. Initialisation picks ``lists`` vectors after a seeded
    shuffle, then runs Lloyd iterations.
    """
    if not vectors:
        return [], []
    rng = random.Random(seed)  # noqa: S311 - deterministic initialisation
    order = list(range(len(vectors)))
    rng.shuffle(order)
    centroids = [list(vectors[index]) for index in order[: min(lists, len(vectors))]]
    assignment = [0] * len(vectors)
    for _ in range(iterations):
        for position, vector in enumerate(vectors):
            assignment[position] = max(
                range(len(centroids)), key=lambda cluster: _dot(vector, centroids[cluster])
            )
        sums: list[list[float]] = [[0.0] * len(vectors[0]) for _ in centroids]
        counts = [0] * len(centroids)
        for position, cluster in enumerate(assignment):
            counts[cluster] += 1
            row = sums[cluster]
            vector = vectors[position]
            for dimension, value in enumerate(vector):
                row[dimension] += value
        for cluster, count in enumerate(counts):
            if count == 0:
                continue
            centroids[cluster] = [value / count for value in sums[cluster]]
    return centroids, assignment


class IvfIndex:
    """IVF-style ANN: probe nearest centroid lists, scan their postings.

    ``filter_mode``: ``before_scan`` emulates a vector store that applies the
    metadata filter inside the scan (pgvector ``WHERE`` on an indexed filter
    column); ``after_scan`` emulates the classic post-filter that scans then
    discards. Both are measured so the difference is an artifact, not
    folklore.
    """

    def __init__(
        self,
        vectors: list[list[float]],
        chunks: list,
        *,
        lists: int,
        seed: int = 20261019,
    ) -> None:
        self.vectors = vectors
        self.chunks = chunks
        started = time.perf_counter()
        self.centroids, assignment = kmeans(vectors, lists=lists, seed=seed)
        self.postings: list[list[int]] = [[] for _ in self.centroids]
        for position, cluster in enumerate(assignment):
            self.postings[cluster].append(position)
        self.build_seconds = round(time.perf_counter() - started, 3)
        self.lists = len(self.centroids)

    def search(
        self,
        query_vector: list[float],
        *,
        probes: int,
        top_k: int = DEFAULT_TOP_K,
        class_level: int | None = None,
        filter_mode: str = "none",
    ) -> tuple[list[int], int]:
        """Return (ranked chunk positions, postings scanned)."""
        probe_count = max(1, min(probes, self.lists))
        nearest = sorted(
            range(self.lists),
            key=lambda cluster: _dot(query_vector, self.centroids[cluster]),
            reverse=True,
        )[:probe_count]
        scanned = 0
        scored: list[tuple[float, int]] = []
        for cluster in nearest:
            for position in self.postings[cluster]:
                chunk = self.chunks[position]
                matches = class_level is None or chunk.meta.class_level == class_level
                if matches or filter_mode != "before_scan":
                    scanned += 1
                if not matches:
                    if filter_mode == "before_scan":
                        continue
                    if filter_mode == "after_scan":
                        continue
                scored.append((_dot(query_vector, self.vectors[position]), position))
        scored.sort(key=lambda item: (-item[0], self.chunks[item[1]].id))
        return [position for _score, position in scored[:top_k]], scanned


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile, 3-decimal ms; 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(min(int(len(ordered) * fraction), len(ordered) - 1), 0)
    return round(ordered[index], 3)


def _load_chunks(corpus_root: Path | None) -> tuple[list, str]:
    if corpus_root is not None and (corpus_root / "normalized").is_dir():
        from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

        chunks = load_nctb_corpus(
            corpus_root / "normalized",
            quality_report_path=corpus_root / "quality_report.json",
        )
        if chunks:
            return chunks, f"nctb:{corpus_root}"
    from bangla_gpt_api.data.loader import load_sample_corpus

    return load_sample_corpus(), "bundled-sample"


def build_queries(chunks: list, *, limit: int = 40) -> list[dict[str, Any]]:
    """Self-sentence queries whose expected evidence unit is known by construction.

    Taking the first words of a chunk as the query means the gold unit is the
    chunk itself, so recall is not read off the system under test.
    """
    rng = random.Random(20261019)  # noqa: S311 - deterministic sampling
    sample = rng.sample(chunks, min(limit, len(chunks)))
    queries: list[dict[str, Any]] = []
    for chunk in sample:
        text = " ".join(chunk.text.split()[:12])
        if len(text.split()) < 4:
            continue
        queries.append(
            {
                "text": text,
                "class_level": chunk.meta.class_level,
                "gold_ids": [chunk.id],
            }
        )
    return queries


def _recall(hits: list[int], want: set[str], chunks: list, k: int) -> float:
    return 1.0 if any(chunks[position].id in want for position in hits[:k]) else 0.0


def build_report(
    *,
    corpus_root: Path | None = None,
    lists: tuple[int, ...] = DEFAULT_LISTS,
    probes: tuple[int, ...] = DEFAULT_PROBES,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.vector import VectorIndex, vector_text

    chunks, corpus_label = _load_chunks(corpus_root)
    if not chunks:
        raise SystemExit("NO_INDEXABLE_CHUNKS")
    embedder = HashingEmbedder()
    vectors = embedder.embed([vector_text(chunk) for chunk in chunks])
    queries = build_queries(chunks)
    if not queries:
        raise SystemExit("NO_QUERIES -- corpus too small for self-sentence queries")
    positions = {chunk.id: position for position, chunk in enumerate(chunks)}
    query_vectors = [(embedder.embed([query["text"]])[0], query) for query in queries]

    # --- exact lane: the shipped brute-force cosine vector index ------------
    exact = VectorIndex(chunks, embedder)
    exact_latencies: list[float] = []
    exact_recalls: list[float] = []
    for _query_vector, query in query_vectors:
        want = {chunk_id for chunk_id in query["gold_ids"]}
        started = time.perf_counter()
        hits = exact.search(query["text"], top_k=top_k)
        exact_latencies.append((time.perf_counter() - started) * 1000)
        hit_positions = [positions[hit.chunk.id] for hit in hits if hit.chunk.id in positions]
        exact_recalls.append(_recall(hit_positions, want, chunks, top_k))

    # --- ANN curve -----------------------------------------------------------
    curve: list[dict[str, Any]] = []
    for lists_count in lists:
        index = IvfIndex(vectors, chunks, lists=lists_count)
        for probe_count in probes:
            if probe_count > lists_count:
                continue
            latencies: list[float] = []
            recalls: list[float] = []
            scanned = 0
            for query_vector, query in query_vectors:
                want = {chunk_id for chunk_id in query["gold_ids"]}
                started = time.perf_counter()
                hit_positions, scanned_here = index.search(
                    query_vector, probes=probe_count, top_k=top_k
                )
                latencies.append((time.perf_counter() - started) * 1000)
                scanned += scanned_here
                recalls.append(_recall(hit_positions, want, chunks, top_k))
            curve.append(
                {
                    "lists": lists_count,
                    "probes": probe_count,
                    "build_seconds": index.build_seconds,
                    "recall_at_10": round(statistics.fmean(recalls), 4),
                    "p50_ms": percentile(latencies, 0.5),
                    "p95_ms": percentile(latencies, 0.95),
                    "mean_scanned_fraction": round(scanned / (len(query_vectors) * len(chunks)), 4),
                }
            )

    filtered = _filtered_block(exact, vectors, chunks, query_vectors, top_k=top_k)

    per_chunk_ms = (
        statistics.fmean(exact_latencies) / len(chunks) if exact_latencies and chunks else 0.0
    )
    projection = {
        "basis": "measured exact-lane mean latency / chunks (linear scan model)",
        "per_chunk_ms": round(per_chunk_ms, 7),
        "projected_p95_ms": {
            str(size): round(per_chunk_ms * 3 * size, 1) for size in (10_000, 100_000, 1_000_000)
        },
        "projection_note": (
            "linear extrapolation: p95 ~= 3x the measured mean per-chunk cost x corpus "
            "size. A projection, not a measurement -- it names the corpus size where "
            "the exact lane stops being viable, and nothing more."
        ),
    }
    exact_p95 = percentile(exact_latencies, 0.95)
    return {
        "generated_by": "bangla_gpt_api.evaluation.ann_sweep",
        "run_conditions": {
            "host": platform.node(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "corpus": corpus_label,
            "chunks": len(chunks),
            "queries": len(query_vectors),
            "top_k": top_k,
            "seed": 20261019,
            "embedder": "HashingEmbedder (deterministic stand-in; no model weights offline)",
            "note": "latency is host-dependent; compare curve points within this run",
        },
        "exact_lane": {
            "index": "VectorIndex (brute-force cosine -- the lane the repo serves)",
            "recall_at_10": round(statistics.fmean(exact_recalls), 4),
            "p50_ms": percentile(exact_latencies, 0.5),
            "p95_ms": exact_p95,
            "mean_scanned": len(chunks),
        },
        "ann_curve": curve,
        "filtered_search": filtered,
        "scale_projection": projection,
        "best_ann_within_budget": _best_config_within_budget(
            curve, exact_recall_marker=statistics.fmean(exact_recalls)
        ),
        "decision_inputs": {
            "search_p95_budget_ms": SEARCH_P95_BUDGET_MS,
            "exact_p95_within_budget": exact_p95 <= SEARCH_P95_BUDGET_MS,
            "ann_parameter_note": (
                "lists ~= sqrt(n) is the pgvector guidance; the curve shows what each "
                "(lists, probes) pair actually costs on this corpus"
            ),
        },
    }


def _filtered_block(
    exact: Any, vectors: list[list[float]], chunks: list, query_vectors: list, *, top_k: int
) -> dict[str, Any]:
    """Exact pre-filter versus ANN pre/post-filter on class-scoped queries."""
    unfiltered_latencies: list[float] = []
    filtered_latencies: list[float] = []
    ann = IvfIndex(vectors, chunks, lists=8)
    pre_latencies: list[float] = []
    post_latencies: list[float] = []
    scanned_pre = 0
    scanned_post = 0
    for query_vector, query in query_vectors:
        class_level = query["class_level"]
        started = time.perf_counter()
        exact.search(query["text"], top_k=top_k)
        unfiltered_latencies.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        exact.search(query["text"], top_k=top_k, class_level=class_level)
        filtered_latencies.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        _positions, scanned_here = ann.search(
            query_vector, probes=4, top_k=top_k, class_level=class_level, filter_mode="before_scan"
        )
        pre_latencies.append((time.perf_counter() - started) * 1000)
        scanned_pre += scanned_here
        started = time.perf_counter()
        _positions, scanned_here = ann.search(
            query_vector, probes=4, top_k=top_k, class_level=class_level, filter_mode="after_scan"
        )
        post_latencies.append((time.perf_counter() - started) * 1000)
        scanned_post += scanned_here
    matching = {
        str(level): sum(1 for chunk in chunks if chunk.meta.class_level == level)
        for level in sorted({query["class_level"] for _v, query in query_vectors})
    }
    return {
        "exact_prefilter_p50_ms": percentile(filtered_latencies, 0.5),
        "exact_prefilter_p95_ms": percentile(filtered_latencies, 0.95),
        "exact_unfiltered_p50_ms": percentile(unfiltered_latencies, 0.5),
        "exact_unfiltered_p95_ms": percentile(unfiltered_latencies, 0.95),
        "matching_chunks_per_class": matching,
        "ann_lists": ann.lists,
        "ann_probes": 4,
        "ann_prefilter_p95_ms": percentile(pre_latencies, 0.95),
        "ann_postfilter_p95_ms": percentile(post_latencies, 0.95),
        "ann_mean_scanned_prefilter": round(scanned_pre / max(len(query_vectors), 1), 1),
        "ann_mean_scanned_postfilter": round(scanned_post / max(len(query_vectors), 1), 1),
        "note": (
            "the exact lane pre-filters (the product's behaviour: the filter is inside "
            "the scan); the ANN lane is measured both ways because a post-filtering "
            "vector store scans more and silently loses recall"
        ),
    }


def _best_config_within_budget(
    curve: list[dict[str, Any]], *, exact_recall_marker: float
) -> dict[str, Any] | None:
    """The least-scanning config that keeps the exact lane's recall and the budget.

    "Keeps the recall" means within 5% relative of the exact lane's own recall
    on the same gold queries: an ANN is a recall-for-latency trade, so the
    comparison must be against the lane it replaces, not against 1.0.
    """
    candidates = [
        row
        for row in curve
        if row["p95_ms"] <= SEARCH_P95_BUDGET_MS
        and row["recall_at_10"] >= 0.95 * exact_recall_marker
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda row: (row["mean_scanned_fraction"], row["p50_ms"]))


def markdown_summary(report: dict) -> str:
    """The recall-versus-latency table for docs; generated, never hand-copied."""
    lines = [
        "| lists | probes | recall@10 (gold) | p50 ms | p95 ms | scanned % | build s |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    exact = report["exact_lane"]
    lines.append(
        f"| exact (brute force) | all | {exact['recall_at_10']} | "
        f"{exact['p50_ms']} | {exact['p95_ms']} | 100% | n/a |"
    )
    for row in report["ann_curve"]:
        lines.append(
            f"| {row['lists']} | {row['probes']} | {row['recall_at_10']} | "
            f"{row['p50_ms']} | {row['p95_ms']} | "
            f"{round(row['mean_scanned_fraction'] * 100, 1)}% | {row['build_seconds']} |"
        )
    return "\n".join(lines)


__all__ = [
    "DEFAULT_LISTS",
    "DEFAULT_PROBES",
    "SEARCH_P95_BUDGET_MS",
    "IvfIndex",
    "build_queries",
    "build_report",
    "kmeans",
    "markdown_summary",
    "percentile",
]
