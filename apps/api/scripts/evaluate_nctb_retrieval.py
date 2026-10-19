"""Retrieval evaluation over the built NCTB corpus (no LLM required).

Measures the index production actually serves — the hybrid lane, matching
``retrieval_mode="hybrid"`` — against every query family, with the lexical,
vector and fusion-without-rerank lanes alongside as attributable baselines:

  A self-sentence: first words of a chunk must retrieve that chunk
  B chapter-title: a real chapter name should surface its own chunks
  C adversarial: out-of-curriculum questions must score below the
                    TutorService grounding gate (refusal = correct)
  D banglish: the romanised form of a self-sentence (the script students
                    actually type) must retrieve the same chunk

Metrics per variant and family: Recall@1/@3/@5/@10, nDCG@10, MRR, each with
a 95% bootstrap confidence interval over the query sample. Latency is
reported p50/p95 per variant with the run's conditions (host, corpus size,
build time, query count) because latency is host-dependent and a number
without its conditions is not evidence.

Also emitted, because the audit found them unmeasured:

* ``gate_threshold_calibration`` — the TutorService grounding-gate pass
  rate of answerable (family A) versus adversarial (family C) questions at
  every candidate threshold, so the hard-coded 0.5 is a measured choice;
* ``lexicon_audit`` — stem-collision groups and curated expansion targets
  that the served corpus actually contains (AUD-A1-20);
* ``index_footprint`` — tracemalloc-measured build memory plus the served
  chunk/duplicate counts (AUD-A1-22, AUD-A1-06).

Outputs data/nctb/retrieval_eval.json by default (``--out PATH`` redirects it,
which is how the one-command harness writes into an untracked directory); the
corpus text itself is NCTB source material and stays out of the repository
(data/nctb/raw|extracted|normalized are gitignored — see
docs/NCTB_DATA_PIPELINE.md), so the committed retrieval_eval.json IS this
script's regression baseline: regenerate it locally with an explicit
``--out`` (or after a deliberate retrieval change) and read the diff.
"""

from __future__ import annotations

import json
import math
import platform
import random
import socket
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

BOOTSTRAP_RESAMPLES = 1000
DEFAULT_SEED = 20260825
GATE_THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)
MAX_TOP_K = 10


def mean(values: list[float]) -> float:
    """Arithmetic mean at report precision; empty inputs are 0, not NaN."""
    return round(sum(values) / len(values), 4) if values else 0.0


def mrr(ranks: list[int]) -> float:
    """Mean reciprocal rank; rank 0 means "not in top-k" and contributes 0."""
    return round(sum(1.0 / rank for rank in ranks if rank > 0) / len(ranks), 4) if ranks else 0.0


def ndcg_at(ranks: list[int], k: int = MAX_TOP_K) -> float:
    """nDCG@k with binary relevance and one relevant document per query.

    IDCG is 1 (the single relevant document at rank 1), so each query
    contributes ``1/log2(rank+1)`` for a hit inside the top-k and 0
    otherwise. Graded relevance would need judgments the corpus does not
    carry.
    """
    if not ranks:
        return 0.0
    gains = [1.0 / math.log2(rank + 1) if 0 < rank <= k else 0.0 for rank in ranks]
    return round(sum(gains) / len(ranks), 4)


def bootstrap_ci(
    values: list[float], *, seed: int, resamples: int = BOOTSTRAP_RESAMPLES
) -> list[float]:
    """Percentile 95% CI of the mean by resampling queries with replacement."""
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(resamples):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return [round(means[int(0.025 * resamples)], 4), round(means[int(0.975 * resamples)], 4)]


def paired_bootstrap_ci(
    diffs: list[float], *, seed: int, resamples: int = BOOTSTRAP_RESAMPLES
) -> list[float]:
    """95% CI of the mean paired difference (A4-04's Banglish gap).

    The same chunk is queried in Bangla and in its romanised form, so the
    difference is paired per chunk; resampling *pairs* keeps the per-chunk
    difficulty out of the interval instead of inflating it.
    """
    if not diffs:
        return [0.0, 0.0]
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(resamples):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return [round(means[int(0.025 * resamples)], 4), round(means[int(0.975 * resamples)], 4)]


def evidence_unit(hit_id: str) -> str:
    """Chunk ids of one page range share an evidence unit."""
    return hit_id.rsplit("-c", 1)[0]


def _rank_of(hits: list, wanted_units: set[str]) -> int:
    """1-based best rank of the wanted evidence unit; 0 when absent."""
    for position, hit in enumerate(hits, start=1):
        if evidence_unit(hit.chunk.id) in wanted_units:
            return position
    return 0


def _recall_at_1(matched_ranks: list[int]) -> float:
    """1.0 only when the wanted evidence unit sits at rank 1.

    ``matched_ranks`` holds the 1-based positions where the evidence unit
    occurred in the top-k; membership alone is Recall@k, not Recall@1.
    """
    return 1.0 if matched_ranks and matched_ranks[0] == 1 else 0.0


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile over the samples (ms), 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(min(int(len(ordered) * fraction), len(ordered) - 1), 0)
    return round(ordered[index] * 1000, 2)


def _metric_block(ranks: list[int], *, seed: int) -> dict[str, Any]:
    """Recall@1/3/5/10 + nDCG@10 + MRR with bootstrap CIs on the headline two."""
    hits = {k: [1.0 if 0 < rank <= k else 0.0 for rank in ranks] for k in (1, 3, 5, 10)}
    ndcg_values = [1.0 / math.log2(rank + 1) if 0 < rank <= MAX_TOP_K else 0.0 for rank in ranks]
    return {
        "n": len(ranks),
        "recall_at_1": mean(hits[1]),
        "recall_at_3": mean(hits[3]),
        "recall_at_5": mean(hits[5]),
        "recall_at_10": mean(hits[10]),
        "ndcg_at_10": mean(ndcg_values),
        "mrr": mrr(ranks),
        "recall_at_1_ci95": bootstrap_ci(hits[1], seed=seed),
        "ndcg_at_10_ci95": bootstrap_ci(ndcg_values, seed=seed),
    }


class RerankVariant:
    """The served lanes and fusion with a different reranker.

    Building a second HybridIndex would rebuild BM25 + vector + vocabulary
    (tens of seconds on the real corpus) for a stage that is a pure function
    of the fused candidates, so the variant swaps the reranker around each
    search instead. Single-threaded evaluation only.
    """

    def __init__(self, hybrid: Any, reranker: Any, name: str) -> None:
        self.hybrid = hybrid
        self.reranker = reranker
        self.name = name
        self.chunks = hybrid.chunks

    def search(self, query: str, **kwargs: Any) -> list[Any]:
        original = self.hybrid.reranker
        self.hybrid.reranker = self.reranker
        try:
            return self.hybrid.search(query, **kwargs)
        finally:
            self.hybrid.reranker = original


def rrf_only_rerank(_query: str, candidates: list[tuple[Any, float, float]]) -> list[float]:
    """Fusion score only: no coverage, proximity or trigram features."""
    return [rrf + lexical_base for _chunk, rrf, lexical_base in candidates]


def _banglish_query(text: str, words: int = 10) -> str:
    """Romanise the opening words of a chunk the way a student would type."""
    from bangla_gpt_api.retrieval.transliteration import to_roman

    return to_roman(" ".join(text.split()[:words]))


def _duplicate_text_groups(chunks: list) -> int:
    """Texts served under more than one class label.

    Informational: the class-range fallback legitimately serves one passage
    for each class in a level's range, so this counts labels, not defects.
    """
    classes: dict[str, set[int]] = {}
    for chunk in chunks:
        key = " ".join(chunk.text.split())
        classes.setdefault(key, set()).add(chunk.meta.class_level)
    return sum(1 for labels in classes.values() if len(labels) > 1)


def _duplicate_class_text_pairs(chunks: list) -> int:
    """Served (class_level, text) pairs beyond the first — the invariant the
    loader's dedupe enforces; anything but 0 is a regression (AUD-A1-06)."""
    seen: set[tuple[int, str]] = set()
    duplicates = 0
    for chunk in chunks:
        pair = (chunk.meta.class_level, " ".join(chunk.text.split()))
        if pair in seen:
            duplicates += 1
        else:
            seen.add(pair)
    return duplicates


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = sys.argv[1:]
    out_path: Path | None = None
    # ``--out PATH`` redirects the artifact (A8-10: the one-command harness
    # writes into an untracked directory and must not dirty this committed
    # file). Everything else keeps the historical positional form the tests
    # and docs use.
    if "--out" in args:
        index = args.index("--out")
        if index + 1 >= len(args):
            print("--out needs a PATH")
            return 1
        out_path = Path(args[index + 1])
        args = args[:index] + args[index + 2 :]
    corpus_root = Path(args[0]) if args else Path("../../data/nctb")
    seed = int(args[1]) if len(args) > 1 else DEFAULT_SEED
    load_stats: dict[str, int] = {}
    chunks = load_nctb_corpus(
        corpus_root / "normalized",
        quality_report_path=corpus_root / "quality_report.json",
        multi_class_fallback=True,
        stats=load_stats,
    )
    if not chunks:
        print("NO_INDEXABLE_CHUNKS — run build_nctb_corpus.py first")
        return 1

    from bangla_gpt_api.retrieval.bm25 import BM25Index
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    tracemalloc.start()
    build_start = time.perf_counter()
    lexical = BM25Index(chunks)
    served = HybridIndex(chunks, HashingEmbedder())
    build_seconds = round(time.perf_counter() - build_start, 3)
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"index built: {len(chunks)} chunks in {build_seconds}s")

    variants: dict[str, Any] = {
        "lexical": lexical,
        "vector": served.vector,
        "hybrid-no-rerank": RerankVariant(served, rrf_only_rerank, "hybrid-no-rerank"),
        "hybrid": served,
    }
    rng = random.Random(seed)

    # --- Family A: self-sentence retrieval ---------------------------------
    #
    # The first words of a chunk are the question; the same chunk (its
    # evidence unit) is the only correct answer.
    queries_a = []
    for chunk in rng.sample(chunks, min(100, len(chunks))):
        query = " ".join(chunk.text.split()[:12])
        if len(query.split()) < 4:
            continue
        queries_a.append((query, chunk, chunk.meta.class_level))
    queries_d = [
        (_banglish_query(chunk.text), chunk, class_level) for _q, chunk, class_level in queries_a
    ]

    ranks: dict[str, dict[str, list[int]]] = {
        name: {"A": [], "B": [], "D": []} for name in variants
    }
    latencies: dict[str, list[float]] = {name: [] for name in variants}
    for name, index in variants.items():
        for query, chunk, class_level in queries_a:
            start = time.perf_counter()
            hits = index.search(query, class_level=class_level, top_k=MAX_TOP_K)
            latencies[name].append(time.perf_counter() - start)
            ranks[name]["A"].append(_rank_of(hits, {evidence_unit(chunk.id)}))
        for query, chunk, class_level in queries_d:
            hits = index.search(query, class_level=class_level, top_k=MAX_TOP_K)
            ranks[name]["D"].append(_rank_of(hits, {evidence_unit(chunk.id)}))

    # --- Family B: chapter-title retrieval ---------------------------------
    #
    # A real chapter name should surface the chunks of that chapter.
    chapters: dict[tuple[int, str], set[str]] = {}
    for chunk in chunks:
        if chunk.meta.chapter:
            key = (chunk.meta.class_level, chunk.meta.chapter.strip())
            chapters.setdefault(key, set()).add(chunk.id.rsplit("-c", 1)[0])
    chapter_keys = list(chapters)
    rng.shuffle(chapter_keys)
    chapter_keys = chapter_keys[:80]
    for name, index in variants.items():
        for class_level, title in chapter_keys:
            hits = index.search(title, class_level=class_level, top_k=MAX_TOP_K)
            ranks[name]["B"].append(_rank_of(hits, chapters[(class_level, title)]))

    # --- Family C: adversarial / out-of-corpus refusals ---------------------
    from bangla_gpt_api.providers.mock import MockLLMProvider
    from bangla_gpt_api.services.tutor import TutorService

    tutor = TutorService(index=served, provider=MockLLMProvider(), term_stats=served.term_stats)
    adversarial = [
        "ক্রিকেট বিশ্বকাপ ফাইনালে কে জিতেছিল?",
        "ঢাকার সেরা বিরিয়ানির দোকান কোথায়?",
        "ইউক্লিডের পঞ্চম স্বতঃসিদ্ধ ব্যাখ্যা কর",  # not in these books
        "গত সপ্তাহের ডলারের দাম কত?",
    ]
    gate_pass = 0
    for question in adversarial:
        # exactly the ask() decision: retrieve, then the coverage gate.
        hits = tutor._retrieve(question, class_level=6, subject=None)
        top_score = hits[0].score if hits else None
        refused = not tutor._gate(question, hits)
        gate_pass += refused
        print(f"  adversarial '{question[:30]}…' top={top_score} refused={refused}")

    # --- Gate calibration: answerable vs adversarial pass rate (A1-15) ------
    answerable_coverage = [
        tutor._coverage_details(query, served.search(query, class_level=class_level, top_k=3))[0]
        for query, _chunk, class_level in queries_a[:50]
    ]
    adversarial_coverage = [
        tutor._coverage_details(question, tutor._retrieve(question, class_level=6, subject=None))[0]
        for question in adversarial
    ]
    calibration = {
        "min_coverage_default": tutor.min_coverage,
        "answerable_mean_coverage": mean(answerable_coverage),
        "adversarial_mean_coverage": mean(adversarial_coverage),
        "thresholds": {
            str(threshold): {
                "answerable_pass_rate": round(
                    sum(1 for value in answerable_coverage if value >= threshold)
                    / len(answerable_coverage),
                    4,
                ),
                "adversarial_pass_rate": round(
                    sum(1 for value in adversarial_coverage if value >= threshold)
                    / len(adversarial_coverage),
                    4,
                ),
            }
            for threshold in GATE_THRESHOLDS
        },
    }

    # --- Lexicon audit (A1-20) ---------------------------------------------
    from bangla_gpt_api.retrieval.hybrid import QUERY_EXPANSIONS, light_stem, tokenize

    stems: dict[str, set[str]] = {}
    for chunk in chunks:
        for token in tokenize(chunk.text):
            stems.setdefault(light_stem(token), set()).add(token)
    collisions = {stem: forms for stem, forms in stems.items() if len(forms) > 1}
    term_stats = served.term_stats
    expansion_targets = sorted({t for targets in QUERY_EXPANSIONS.values() for t in targets})
    absent_targets = [
        target
        for target in expansion_targets
        if term_stats is None or term_stats.document_frequency(light_stem(target)) == 0
    ]
    lexicon_audit = {
        "stem_groups": len(stems),
        "collision_groups": len(collisions),
        "collision_ratio": round(len(collisions) / len(stems), 4) if stems else 0.0,
        "collision_examples": {
            stem: sorted(forms) for stem, forms in sorted(collisions.items())[:5]
        },
        "expansion_targets": len(expansion_targets),
        "expansion_targets_absent_from_corpus": absent_targets,
        "expansion_targets_absent_count": len(absent_targets),
    }

    # --- Banglish subset metric (A4-04) ------------------------------------
    #
    # Family D is family A romanised: the same chunks, the script students
    # actually type. The subset metric is the paired recall@5 difference, so
    # "the roman lane costs X points" is a number with an interval, not an
    # anecdote. Family labels come from the shipped detector
    # (retrieval/langid.classify_query), not from a hand-assigned list.
    from bangla_gpt_api.retrieval.langid import classify_query

    vocabulary = getattr(getattr(served, "bm25", None), "term_stats", None)

    def _roman_matches(text: str) -> list[str]:
        if vocabulary is None or not hasattr(vocabulary, "match_roman"):
            return []
        return [match for token in text.split() for match in vocabulary.match_roman(token)]

    labels_a = [
        classify_query(query, roman_matches=_roman_matches(query)) for query, _c, _l in queries_a
    ]
    labels_d = [
        classify_query(query, roman_matches=_roman_matches(query)) for query, _c, _l in queries_d
    ]
    values_a = [1.0 if 0 < rank <= 5 else 0.0 for rank in ranks["hybrid"]["A"]]
    values_d = [1.0 if 0 < rank <= 5 else 0.0 for rank in ranks["hybrid"]["D"]]
    paired_diffs = [d - a for a, d in zip(values_a, values_d, strict=True)]
    banglish_gap = {
        "n_pairs": len(paired_diffs),
        "recall_at_5_bangla": mean(values_a),
        "recall_at_5_banglish": mean(values_d),
        "paired_delta_banglish_minus_bangla": mean(paired_diffs),
        "paired_delta_ci95": paired_bootstrap_ci(paired_diffs, seed=seed),
        "delta_definition": (
            "mean over chunks of (recall@5 on the romanised form - recall@5 on the "
            "Bangla form); a negative value is the roman lane's cost"
        ),
        "labels_family_a": sorted(
            {label: labels_a.count(label) for label in set(labels_a)}.items()
        ),
        "labels_family_d": sorted(
            {label: labels_d.count(label) for label in set(labels_d)}.items()
        ),
    }

    report: dict[str, Any] = {
        "corpus_chunks": len(chunks),
        "index_build_seconds": build_seconds,
        "served_index": "hybrid",
        "run_conditions": {
            "seed": seed,
            "host": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "queries_family_a": len(queries_a),
            "queries_family_b": len(chapter_keys),
            "queries_family_d_banglish": len(queries_d),
            "top_k_evaluated": MAX_TOP_K,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        },
        "serve_stats": {
            "duplicates_dropped_at_load": load_stats.get("duplicates_dropped", 0),
            "latin_residue_drops": load_stats.get("latin_residue_drops", 0),
            "legacy_drops": load_stats.get("legacy_drops", 0),
            "served_duplicate_text_groups": _duplicate_text_groups(chunks),
            "served_duplicate_class_text_pairs": _duplicate_class_text_pairs(chunks),
        },
        "family_A_self_sentence": _metric_block(ranks["hybrid"]["A"], seed=seed),
        "family_B_chapter_title": _metric_block(ranks["hybrid"]["B"], seed=seed),
        "family_D_banglish": _metric_block(ranks["hybrid"]["D"], seed=seed),
        "family_C_adversarial_refusal_rate": round(gate_pass / len(adversarial), 4),
        "search_latency_p50_ms": percentile(latencies["hybrid"], 0.5),
        "search_latency_p95_ms": percentile(latencies["hybrid"], 0.95),
        "baseline_lexical": {
            "family_A_self_sentence": _metric_block(ranks["lexical"]["A"], seed=seed),
            "family_B_chapter_title": _metric_block(ranks["lexical"]["B"], seed=seed),
        },
        "variants": {
            name: {
                family: _metric_block(ranks[name][family], seed=seed) for family in ("A", "B", "D")
            }
            | {
                "latency": {
                    "p50_ms": percentile(latencies[name], 0.5),
                    "p95_ms": percentile(latencies[name], 0.95),
                }
            }
            for name in variants
        },
        "gate_threshold_calibration": calibration,
        "lexicon_audit": lexicon_audit,
        "banglish_subset": banglish_gap,
        "index_footprint": {
            "build_peak_memory_mb": round(peak_bytes / (1024 * 1024), 2),
            "chunks": len(chunks),
            "chunks_per_second_of_build": round(len(chunks) / max(build_seconds, 0.001), 1),
        },
    }
    out = out_path or (corpus_root / "retrieval_eval.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    # trailing newline: the pre-commit end-of-file-fixer requires it, and a
    # Windows text-mode write will not add one on its own.
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # The Markdown the docs quote is printed from the report, so the table is
    # pasted verbatim instead of re-typed (and cannot drift from the JSON).
    print("\nMarkdown for docs/RAG_ARCHITECTURE.md:\n")
    print(_markdown_summary(report))
    return 0


def _markdown_summary(report: dict) -> str:
    lines = ["| Metric | Committed artifact |", "|---|---|"]
    lines.append(f"| Corpus chunks served | {report['corpus_chunks']} |")
    lines.append(f"| Index build | {report['index_build_seconds']} s |")
    for key in ("family_A_self_sentence", "family_B_chapter_title", "family_D_banglish"):
        block = report[key]
        lines.append(
            f"| {key} (n={block['n']}) recall@1 / @3 / @5 / @10 | "
            f"{block['recall_at_1']} / {block['recall_at_3']} / {block['recall_at_5']} / "
            f"{block['recall_at_10']} |"
        )
        lines.append(f"| {key} nDCG@10 / MRR | {block['ndcg_at_10']} / {block['mrr']} |")
        lines.append(
            f"| {key} CI95 (recall@1 / nDCG@10) | "
            f"{block['recall_at_1_ci95']} / {block['ndcg_at_10_ci95']} |"
        )
    lines.append(
        f"| Adversarial refusal rate (family C) | {report['family_C_adversarial_refusal_rate']} |"
    )
    lines.append(
        f"| Search latency p50 / p95 (hybrid) | {report['search_latency_p50_ms']} ms / "
        f"{report['search_latency_p95_ms']} ms |"
    )
    lines.append(
        f"| Index build peak memory | {report['index_footprint']['build_peak_memory_mb']} MB |"
    )
    lines.append("")
    lines.append("| Variant | A recall@1 | A nDCG@10 | B recall@1 | D recall@1 | p50 ms | p95 ms |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, block in report["variants"].items():
        lines.append(
            f"| {name} | {block['A']['recall_at_1']} | {block['A']['ndcg_at_10']} | "
            f"{block['B']['recall_at_1']} | {block['D']['recall_at_1']} | "
            f"{block['latency']['p50_ms']} | {block['latency']['p95_ms']} |"
        )
    conditions = report["run_conditions"]
    lines.append("")
    lines.append(
        f"Run conditions: host {conditions['host']}, {conditions['platform']}, python "
        f"{conditions['python']}, seed {conditions['seed']}, family A n="
        f"{conditions['queries_family_a']}, family B n={conditions['queries_family_b']}, "
        f"family D n={conditions['queries_family_d_banglish']}, top-k "
        f"{conditions['top_k_evaluated']}, {conditions['bootstrap_resamples']} bootstrap resamples."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
