"""Retrieval evaluation over the built NCTB corpus (no LLM required).

Measures the index production actually serves — the hybrid lane, matching
``retrieval_mode="hybrid"`` — against every query family, with the plain
lexical lane alongside as an attributable baseline:

  A self-sentence: first words of a chunk must retrieve that chunk
  B chapter-title: a real chapter name should surface its own chunks
  C adversarial: out-of-curriculum questions must score below the
                    TutorService grounding gate (refusal = correct)

Outputs data/nctb/retrieval_eval.json with Recall@K and MRR per family and
the grounding-gate confusion counts for family C. Every proportion carries a
Wilson 95% interval and the per-item ranks, so two runs can be compared with
a paired bootstrap (``--compare``) instead of eyeballing point estimates
(RAG-22).

``--ablation`` runs the four configurations the architecture claims need
evidence for — lexical only, vector only, hybrid without rerank, hybrid with
rerank — on the same sampled queries, with per-stage latency, and writes
retrieval_ablation.json alongside the report.

``--chunk-stats`` measures the chunk size distribution in the tokenizer the
index uses and the evidence budget's retention (RAG-05/RAG-10).

The corpus text itself is NCTB source material and stays out of the
repository (data/nctb/raw|extracted|normalized are gitignored — see
docs/NCTB_DATA_PIPELINE.md), so the committed retrieval_eval.json IS this
script's regression baseline: regenerate it locally after any retrieval
change and read the diff. The script also finalizes the corpus manifest's
derived digests, so the tracked report and the tracked manifest can be
checked against each other (scripts/check_corpus_manifest.py).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
from bangla_gpt_api.evaluation.stats import interval_report, paired_bootstrap, percentile_report

#: Fixed so a partial run is reproducible; recorded in the report.
EVAL_SEED = 20260825
FAMILY_A_SAMPLE = 100
FAMILY_B_CHAPTERS = 80

ADVERSARIAL_QUESTIONS = [
    "ক্রিকেট বিশ্বকাপ ফাইনালে কে জিতেছিল?",
    "ঢাকার সেরা বিরিয়ানির দোকান কোথায়?",
    "ইউক্লিডের পঞ্চম স্বতঃসিদ্ধ ব্যাখ্যা কর",  # not in these books
    "গত সপ্তাহের ডলারের দাম কত?",
]


def mean(values: list[float]) -> float:
    """Arithmetic mean at report precision; empty inputs are 0, not NaN."""
    return round(sum(values) / len(values), 4) if values else 0.0


def mrr(ranks: Sequence[float]) -> float:
    """Mean reciprocal rank; rank 0 means "not in top-k" and contributes 0.

    ``ranks`` are 1-based positions (integer-valued, hence accepted as
    numbers), the same contract family A and family B feed in.
    """
    return round(sum(1.0 / rank for rank in ranks if rank > 0) / len(ranks), 4) if ranks else 0.0


def evidence_unit(hit_id: str) -> str:
    """Chunk ids of one page range share an evidence unit."""
    return hit_id.rsplit("-c", 1)[0]


def _rank_of(hits, wanted_units: set[str]) -> int:
    """1-based best rank of the wanted evidence unit; 0 when absent."""
    for position, hit in enumerate(hits, start=1):
        if evidence_unit(hit.chunk.id) in wanted_units:
            return position
    return 0


def _block(ranks: list[int]) -> dict[str, Any]:
    """Recall@1/@5, MRR and the Wilson interval of each rate."""
    at_1 = interval_report(sum(1 for rank in ranks if rank == 1), len(ranks))
    at_5 = interval_report(sum(1 for rank in ranks if 0 < rank <= 5), len(ranks))
    return {
        "n": len(ranks),
        "recall_at_1": at_1["rate"],
        "recall_at_5": at_5["rate"],
        "mrr": mrr(ranks),
        "recall_at_1_ci95": [at_1["ci95_low"], at_1["ci95_high"]],
        "recall_at_5_ci95": [at_5["ci95_low"], at_5["ci95_high"]],
    }


def _sample_queries(chunks, sample: int = FAMILY_A_SAMPLE) -> list[tuple[str, int, str]]:
    """(query, class_level, evidence unit) for family A, in run order."""
    rng = random.Random(EVAL_SEED)
    queries: list[tuple[str, int, str]] = []
    for chunk in rng.sample(chunks, min(sample, len(chunks))):
        query = " ".join(chunk.text.split()[:12])
        if len(query.split()) < 4:
            continue
        queries.append((query, chunk.meta.class_level, evidence_unit(chunk.id)))
    return queries


def _chapter_queries(
    chunks, chapters_wanted: int = FAMILY_B_CHAPTERS
) -> list[tuple[str, int, set[str]]]:
    """(title, class_level, wanted units) for family B, in run order."""
    chapters: dict[tuple[int, str], set[str]] = {}
    for chunk in chunks:
        if chunk.meta.chapter:
            key = (chunk.meta.class_level, chunk.meta.chapter.strip())
            chapters.setdefault(key, set()).add(chunk.id.rsplit("-c", 1)[0])
    keys = list(chapters)
    random.Random(EVAL_SEED).shuffle(keys)
    return [
        (title, class_level, chapters[(class_level, title)])
        for class_level, title in keys[:FAMILY_B_CHAPTERS]
    ]


def _latency_ms(latencies: list[float]) -> dict[str, Any]:
    """Percentile report of search latencies, converted to milliseconds."""
    report = percentile_report(latencies, (50, 95))
    return {
        "n": report["n"],
        "p50": round(report["p50"] * 1000, 2),
        "p95": round(report["p95"] * 1000, 2),
    }


def _rank_lists(index, queries, chapters) -> tuple[list[int], list[int], list[float]]:
    """Family A and B ranks (in run order) plus per-query latency seconds."""
    ranks_a: list[int] = []
    latencies: list[float] = []
    for query, class_level, wanted in queries:
        start = time.perf_counter()
        hits = index.search(query, class_level=class_level, top_k=5)
        latencies.append(time.perf_counter() - start)
        ranks_a.append(_rank_of(hits, {wanted}))
    ranks_b: list[int] = []
    for title, class_level, wanted in chapters:
        start = time.perf_counter()
        hits = index.search(title, class_level=class_level, top_k=5)
        latencies.append(time.perf_counter() - start)
        ranks_b.append(_rank_of(hits, wanted))
    return ranks_a, ranks_b, latencies


def _build_indexes(chunks) -> dict[str, Any]:
    from bangla_gpt_api.retrieval.bm25 import BM25Index
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    return {
        "lexical": BM25Index(chunks),
        "served": HybridIndex(chunks, HashingEmbedder()),
    }


def _family_c(tutor) -> tuple[int, list[int]]:
    outcomes: list[int] = []
    for question in ADVERSARIAL_QUESTIONS:
        # exactly the ask() decision: retrieve, then the coverage gate.
        hits = tutor._retrieve(question, class_level=6, subject=None)
        top_score = hits[0].score if hits else None
        refused = not tutor._gate(question, hits)
        outcomes.append(1 if refused else 0)
        print(f"  adversarial '{question[:30]}…' top={top_score} refused={refused}")
    return sum(outcomes), outcomes


def _chunk_stats(chunks) -> dict[str, Any]:
    """Chunk size distribution in production tokens (RAG-05).

    The numbers the chunker's budgets are anchored on: the sizes the index
    actually pays for, measured with the tokenizer it actually uses.
    """
    from bangla_gpt_api.retrieval.context import EVIDENCE_TOKEN_BUDGET
    from bangla_gpt_api.retrieval.hybrid import tokenize

    tokens = [len(tokenize(chunk.text)) for chunk in chunks]
    return {
        "unit": "tokens of retrieval.hybrid.tokenize",
        "chunks": len(tokens),
        "tokens": percentile_report(tokens, (5, 50, 90, 95, 100)),
        "evidence_token_budget": EVIDENCE_TOKEN_BUDGET,
        "chunks_over_evidence_budget": sum(1 for count in tokens if count > EVIDENCE_TOKEN_BUDGET),
    }


def _ablation(chunks, queries, chapters, *, label: str) -> dict[str, Any]:
    """Four retrieval configurations on the same sampled queries."""
    from bangla_gpt_api.retrieval.bm25 import BM25Index
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
    from bangla_gpt_api.retrieval.vector import VectorIndex

    embedder = HashingEmbedder()
    modes: dict[str, dict[str, Any]] = {}

    start = time.perf_counter()
    lexical = BM25Index(chunks)
    modes["lexical_only"] = {
        "index": lexical,
        "build_seconds": round(time.perf_counter() - start, 3),
    }

    start = time.perf_counter()
    vector = VectorIndex(chunks, embedder)
    modes["vector_only"] = {"index": vector, "build_seconds": round(time.perf_counter() - start, 3)}

    start = time.perf_counter()
    fused = HybridIndex(
        chunks,
        embedder,
        reranker=lambda _query, candidates: [
            rrf_score for _chunk, rrf_score, _lexical in candidates
        ],
    )
    modes["hybrid_no_rerank"] = {
        "index": fused,
        "build_seconds": round(time.perf_counter() - start, 3),
    }

    start = time.perf_counter()
    served = HybridIndex(chunks, embedder)
    modes["hybrid_rerank"] = {
        "index": served,
        "build_seconds": round(time.perf_counter() - start, 3),
    }

    report: dict[str, Any] = {
        "n_family_a": len(queries),
        "n_family_b": len(chapters),
        "seed": EVAL_SEED,
        "note": (
            "per-mode index build, recall and search latency on the same sampled "
            "queries; rerank_overhead is the p50 difference between the fused mode "
            "with and without the reranker"
        ),
        "modes": {},
    }
    for name, mode in modes.items():
        ranks_a, ranks_b, latencies = _rank_lists(mode["index"], queries, chapters)
        report["modes"][name] = {
            "index_build_seconds": mode["build_seconds"],
            "family_A_self_sentence": _block(ranks_a),
            "family_B_chapter_title": _block(ranks_b),
            "search_latency_ms": _latency_ms(latencies),
        }
        print(
            f"  ablation {name}: A@1={report['modes'][name]['family_A_self_sentence']['recall_at_1']} "
            f"B@1={report['modes'][name]['family_B_chapter_title']['recall_at_1']} "
            f"p50={report['modes'][name]['search_latency_ms']['p50']}ms"
        )
    p50_fused = report["modes"]["hybrid_no_rerank"]["search_latency_ms"]["p50"]
    p50_rerank = report["modes"]["hybrid_rerank"]["search_latency_ms"]["p50"]
    report["rerank_overhead_p50_ms"] = round(p50_rerank - p50_fused, 2)
    report["label"] = label
    return report


def _corpus_identity(corpus_root: Path, chunks) -> dict[str, Any]:
    """Digest of the served corpus + the manifest it was checked against."""
    from bangla_gpt_api.nctb.manifest import (
        corpus_manifest_path,
        sha256_file,
        verify_corpus_manifest,
    )
    from bangla_gpt_api.retrieval.index_manifest import chunk_files, corpus_digest

    manifest_path = corpus_manifest_path(corpus_root)
    _manifest, _problems = verify_corpus_manifest(
        corpus_root, index_chunks=len(chunks), check_code_fingerprint=False, check_files=True
    )
    return {
        "corpus_digest": corpus_digest(chunk_files(corpus_root)),
        "index_chunks": len(chunks),
        "corpus_manifest_sha256": sha256_file(manifest_path) if manifest_path.exists() else None,
    }


def _index_id_hash(chunks) -> str:
    """Fingerprint of the served index: sha256 over the sorted chunk ids."""
    import hashlib

    digest = hashlib.sha256("|".join(sorted(chunk.id for chunk in chunks)).encode("utf-8"))
    return digest.hexdigest()


def _update_manifest(corpus_root: Path, report: dict[str, Any], *, embedder) -> None:
    """Record this run's digests in the corpus manifest (derived section)."""
    from bangla_gpt_api.nctb.manifest import (
        corpus_manifest_path,
        read_json,
        sha256_file,
        write_json,
    )

    manifest_path = corpus_manifest_path(corpus_root)
    if not manifest_path.exists():
        print("no corpus manifest to finalize; run build_nctb_corpus.py first")
        return
    manifest = read_json(manifest_path)
    derived = manifest.setdefault("derived", {})
    derived["quality_report_sha256"] = (
        sha256_file(corpus_root / "quality_report.json")
        if (corpus_root / "quality_report.json").exists()
        else None
    )
    eval_path = corpus_root / "retrieval_eval.json"
    derived["retrieval_eval_sha256"] = sha256_file(eval_path) if eval_path.exists() else None
    derived["index_chunks"] = report["corpus_chunks"]
    derived["index_id_hash"] = report["index_id_hash"]
    derived["embedder"] = {"name": embedder.name, "dim": getattr(embedder, "dim", None)}
    derived["retrieval_evaluated_at"] = report["evaluated_at"]
    write_json(manifest_path, manifest)
    print(f"manifest derived digests recorded: {manifest_path}")


def _compare(baseline_path: Path, report: dict[str, Any]) -> int:
    """Paired bootstrap of this run against a stored report (same eval set)."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    failures = 0
    for key in ("family_A_self_sentence", "family_B_chapter_title"):
        before = baseline.get("per_item", {}).get(key)
        after = report.get("per_item", {}).get(key)
        if before is None or after is None:
            print(f"{key}: no per-item ranks in one of the reports; cannot pair")
            failures += 1
            continue
        hit_before = [1.0 if rank == 1 else 0.0 for rank in before]
        hit_after = [1.0 if rank == 1 else 0.0 for rank in after]
        result = paired_bootstrap(hit_before, hit_after, seed=EVAL_SEED)
        verdict = "significant" if result["significant"] else "no measurable difference"
        print(
            f"{key}: recall@1 {mean(hit_before):.4f} -> {mean(hit_after):.4f} "
            f"diff {result['mean_diff']:+.4f} "
            f"95% [{result['ci_low']:+.4f}, {result['ci_high']:+.4f}] {verdict}"
        )
    return 1 if failures else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus_root", nargs="?", type=Path, default=Path("../../data/nctb"))
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="load the corpus without cross-source dedupe (ablation for F-012)",
    )
    parser.add_argument("--ablation", action="store_true", help="run the four-configuration table")
    parser.add_argument(
        "--sample",
        type=int,
        default=FAMILY_A_SAMPLE,
        help=f"family A queries to sample (default {FAMILY_A_SAMPLE}; the ablation may use fewer)",
    )
    parser.add_argument(
        "--chapters",
        type=int,
        default=FAMILY_B_CHAPTERS,
        help=f"family B chapter titles to sample (default {FAMILY_B_CHAPTERS})",
    )
    parser.add_argument("--chunk-stats", action="store_true", help="chunk token distribution")
    parser.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="paired bootstrap of this run against a stored retrieval_eval.json",
    )
    parser.add_argument(
        "--label",
        default="",
        help="free-text label recorded in the ablation artifact (e.g. the commit sha)",
    )
    args = parser.parse_args()
    corpus_root: Path = args.corpus_root

    from bangla_gpt_api.retrieval.embedding import HashingEmbedder

    chunks = load_nctb_corpus(
        corpus_root / "normalized",
        quality_report_path=corpus_root / "quality_report.json",
        multi_class_fallback=True,
        dedupe=not args.no_dedupe,
    )
    if not chunks:
        print("NO_INDEXABLE_CHUNKS — run build_nctb_corpus.py first")
        return 1
    identity = _corpus_identity(corpus_root, chunks)
    print(f"index corpus: {len(chunks)} chunks digest={identity['corpus_digest'][:16]}")

    queries = _sample_queries(chunks, args.sample)
    chapters = _chapter_queries(chunks, args.chapters)

    if args.ablation:
        report = _ablation(chunks, queries, chapters, label=args.label)
        out = corpus_root / "retrieval_ablation.json"
        out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + chr(10),
            encoding="utf-8",
            newline="\n",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\nablation written: {out}")
        return 0

    if args.chunk_stats:
        stats = _chunk_stats(chunks)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    build_start = time.perf_counter()
    indexes = _build_indexes(chunks)
    build_seconds = round(time.perf_counter() - build_start, 3)
    print(f"index built: {len(chunks)} chunks in {build_seconds}s")

    ranks_a, ranks_b, latencies = _rank_lists(indexes["served"], queries, chapters)
    lexical_a, lexical_b, _lexical_latencies = _rank_lists(indexes["lexical"], queries, chapters)

    from bangla_gpt_api.providers.mock import MockLLMProvider
    from bangla_gpt_api.services.tutor import TutorService

    tutor = TutorService(
        index=indexes["served"], provider=MockLLMProvider(), term_stats=indexes["served"].term_stats
    )
    gate_pass, outcomes_c = _family_c(tutor)

    latency_report = _latency_ms(latencies)
    refusal_interval = interval_report(gate_pass, len(ADVERSARIAL_QUESTIONS))
    report: dict[str, Any] = {
        "schema_version": 2,
        "evaluated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": EVAL_SEED,
        "corpus_chunks": len(chunks),
        "index_build_seconds": build_seconds,
        "served_index": "hybrid",
        "dedupe_cross_source": not args.no_dedupe,
        "family_A_self_sentence": _block(ranks_a),
        "family_B_chapter_title": _block(ranks_b),
        "family_C_adversarial_refusal_rate": refusal_interval["rate"],
        "family_C_refusal_ci95": [refusal_interval["ci95_low"], refusal_interval["ci95_high"]],
        "search_latency_p50_ms": latency_report["p50"],
        "search_latency_p95_ms": latency_report["p95"],
        "search_latency_n": latency_report["n"],
        "baseline_lexical": {
            "family_A_self_sentence": _block(lexical_a),
            "family_B_chapter_title": _block(lexical_b),
        },
        "per_item": {
            "family_A_self_sentence": ranks_a,
            "family_B_chapter_title": ranks_b,
            "family_C_refusal": outcomes_c,
        },
        "index_id_hash": _index_id_hash(chunks),
        **identity,
    }
    # Guard (F-048): every reported rate/metric is a fraction by construction;
    # a value above 1 means the metric was double-inverted (family B carried
    # exactly that bug) or the block helper was mis-wired.
    for family_key in ("family_A_self_sentence", "family_B_chapter_title"):
        for metric_key, value in report[family_key].items():
            if metric_key in ("n",) or isinstance(value, list):
                continue
            assert 0.0 <= float(value) <= 1.0, (family_key, metric_key, value)
    for variant in report["baseline_lexical"].values():
        for metric_key, value in variant.items():
            if metric_key in ("n",) or isinstance(value, list):
                continue
            assert 0.0 <= float(value) <= 1.0, (metric_key, value)
    out = corpus_root / "retrieval_eval.json"
    # Trailing newline for the end-of-file-fixer, explicit LF because the
    # file is committed and its digest is recorded in the corpus manifest.
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + chr(10),
        encoding="utf-8",
        newline="\n",
    )
    _update_manifest(corpus_root, report, embedder=HashingEmbedder())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    failures = 0
    if args.compare is not None:
        failures = _compare(args.compare, report)
    return failures


if __name__ == "__main__":
    sys.exit(main())
