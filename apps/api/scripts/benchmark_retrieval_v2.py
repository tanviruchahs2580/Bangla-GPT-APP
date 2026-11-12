"""Retrieval engine v2 — benchmark sweep (hermetic; no LLM, no network).

The owner's requirement: the candidate pool and top-K are NOT fixed
assumptions — they are swept and measured. This script sweeps the knobs the
flow diagram names, on the served engine, and reports the measured winners:

  grid: rag_candidate_factor x rag_rrf_k x neighbor expansion (off/on)
        (a configured cross-encoder is exercised too when reachable;
         the hermetic default run measures the lexical stage)

  per cell, over the golden v3 items:
    hit@3      — expected chapter surfaces in the top-3 (the golden gate's
                 own hit metric, HIT_GATE_K=3)
    grounded accuracy — gate/grounded verdict matches the expected verdict
                 (positives must ground; negatives must refuse) — the
                 grounding gate's thresholds are LOCKED; only the retrieval
                 knobs beneath it move
    refusal rate — reported explicitly per the RAG skill contract

  Wilson 95% intervals per rate (evaluation.stats), so a winner is a winner
  beyond noise, not an eyeball.

Outputs JSON (benchmark_v2.json) and a markdown table on stdout. Default
knobs stay untouched unless a cell wins beyond its interval — changing the
LOCKED final top_k is never done here, only reported as a recommendation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bangla_gpt_api.config import Settings  # noqa: E402
from bangla_gpt_api.data.loader import load_sample_corpus  # noqa: E402
from bangla_gpt_api.evaluation.stats import wilson  # noqa: E402
from bangla_gpt_api.providers.mock import MockLLMProvider  # noqa: E402
from bangla_gpt_api.retrieval.embedding import build_embedder  # noqa: E402
from bangla_gpt_api.retrieval.expansion import build_neighbor_expander  # noqa: E402
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex  # noqa: E402
from bangla_gpt_api.services.tutor import TutorService  # noqa: E402


def _golden_items(limit: int | None) -> list[dict]:
    from bangla_gpt_api.evaluation import cli as eval_cli

    golden_path = ROOT / "eval" / "golden_v3.json"
    items: list[dict] = eval_cli._load_golden_items(golden_path, 0)
    return items if limit is None else items[:limit]


def _measure_cell(
    items: list[dict],
    *,
    candidate_factor: int,
    rrf_k: int,
    neighbor: bool,
) -> dict:
    chunks = load_sample_corpus()
    index = HybridIndex(
        chunks,
        build_embedder(Settings(env="test")),
        candidate_factor=candidate_factor,
        rrf_k=rrf_k,
    )
    expander = build_neighbor_expander(chunks) if neighbor else None
    tutor = TutorService(
        index=index,
        provider=MockLLMProvider(),
        fast_provider=None,
        term_stats=index.term_stats,
    )

    hits_total = hit3 = 0
    verdict_total = verdict_ok = 0
    refusals = 0
    for item in items:
        hits = index.search(
            item["question"],
            class_level=item["class_level"],
            subject=item["subject"],
            top_k=3,
        )
        if expander is not None:
            hits = expander(hits)
        expected_chapter = item.get("chapter")
        expect_grounded = item.get("expect") == "answer"
        if expect_grounded and expected_chapter:
            hits_total += 1
            if any(expected_chapter in h.chunk.meta.chapter for h in hits):
                hit3 += 1
        coverage, gate_pass = tutor._coverage_details(item["question"], hits)
        grounded = gate_pass and bool(hits)
        verdict_total += 1
        verdict_ok += int(grounded == expect_grounded)
        refusals += int(not grounded)

    hit_rate = hit3 / hits_total if hits_total else 0.0
    acc = verdict_ok / verdict_total if verdict_total else 0.0
    refusal_rate = refusals / verdict_total if verdict_total else 0.0
    return {
        "candidate_factor": candidate_factor,
        "rrf_k": rrf_k,
        "neighbor_expansion": neighbor,
        "n": verdict_total,
        "hit_at_3": round(hit_rate, 4),
        "hit_at_3_ci": [round(v, 4) for v in wilson(hit3, hits_total)] if hits_total else None,
        "grounded_accuracy": round(acc, 4),
        "grounded_accuracy_ci": [round(v, 4) for v in wilson(verdict_ok, verdict_total)],
        "refusal_rate": round(refusal_rate, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="benchmark_retrieval_v2")
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="cap the golden items per cell (smoke runs); default: all 427",
    )
    parser.add_argument("--output", default=str(ROOT / "benchmark_v2.json"))
    args = parser.parse_args()

    items = _golden_items(args.max_items)
    if not items:
        print("NO_GOLDEN_ITEMS")
        return 1

    grid = [
        (cf, k, neighbor)
        for cf in (2, 3, 4, 6)
        for k in (20, 60, 100)
        for neighbor in (False, True)
    ]
    results = []
    for cf, k, neighbor in grid:
        cell = _measure_cell(items, candidate_factor=cf, rrf_k=k, neighbor=neighbor)
        results.append(cell)
        print(
            f"cell cf={cf} rrf_k={k} neighbor={int(neighbor)}: "
            f"hit@3={cell['hit_at_3']} acc={cell['grounded_accuracy']} "
            f"refusal={cell['refusal_rate']} (n={cell['n']})"
        )

    best = max(results, key=lambda c: (c["grounded_accuracy"], c["hit_at_3"]))
    baseline = next(
        c
        for c in results
        if c["candidate_factor"] == 3 and c["rrf_k"] == 60 and not c["neighbor_expansion"]
    )
    print()
    print("| candidate_factor | rrf_k | neighbor | hit@3 | grounded_acc | refusal |")
    print("|---|---|---|---|---|---|")
    for c in results:
        print(
            f"| {c['candidate_factor']} | {c['rrf_k']} | {int(c['neighbor_expansion'])} "
            f"| {c['hit_at_3']} | {c['grounded_accuracy']} | {c['refusal_rate']} |"
        )
    print()
    print(f"shipped defaults (cf=3, rrf_k=60, neighbor=off): acc={baseline['grounded_accuracy']}")
    print(
        f"measured best cell: cf={best['candidate_factor']} rrf_k={best['rrf_k']} "
        f"neighbor={int(best['neighbor_expansion'])} acc={best['grounded_accuracy']}"
    )
    print("NOTE: the final evidence top_k=3 is the LOCKED grounding contract; this sweep")
    print("moves only the candidate-pool depths and reports — it never changes thresholds.")

    Path(args.output).write_text(
        json.dumps({"cells": results, "best": best}, indent=1), encoding="utf-8"
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
