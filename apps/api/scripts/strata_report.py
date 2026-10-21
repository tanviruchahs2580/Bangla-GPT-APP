r"""A8-03 / AUD-A2-12: stratified retrieval metrics on the golden set.

Measures the retrieval the product serves (``HybridIndex``, the
``retrieval_mode="hybrid"`` lane) against every *positive* item of the frozen
golden set, in two lanes:

* **filtered** -- exactly what the tutor does: search pre-filtered by the
  item's class level and subject;
* **unfiltered** -- the same query with no metadata filter, the lane that
  shows what the filter is buying (or costing) for the same questions.

Gold evidence is derived from the corpus, not from the retrieval system: an
item's gold unit is every chunk whose ``(class_level, subject, section)``
equals the item's own section metadata, which the golden generator recorded
from the corpus (scripts/gen_golden_v2.py). Items whose section cannot be
resolved in the corpus are counted and listed, never silently dropped.

Output: ``apps/api/eval/strata_report.json`` -- committed, deterministic under
the sample corpus (seed, resamples and corpus fingerprint are recorded, no
host-specific timing), so the report is reproducible from a clean checkout:

    cd apps/api
    python scripts/strata_report.py                      # sample corpus (CI-safe)
    python scripts/strata_report.py --corpus-dir ../../data/nctb   # real corpus
    python scripts/strata_report.py --split dev          # tuning view

Every number in docs/evaluation/retrieval-strata.md comes from this file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_GOLDEN = APP_ROOT / "eval" / "golden_v2.json"
DEFAULT_OUT = APP_ROOT / "eval" / "strata_report.json"
DEFAULT_TOP_K = 10
#: Fixed so the committed artifact is byte-stable: the CI, the MDE and the
#: ranking are all seeded from this one value.
DEFAULT_SEED = 20261019
STRATA_KEYS = ("class_level", "subject", "stratum", "split")


def gold_units_by_section(chunks: list) -> dict[tuple[int, str, str], set[str]]:
    """Map ``(class_level, subject, section)`` -> the chunk ids of that section.

    One section can legitimately be served under several class labels by the
    loader's class-range fallback; the set holds every such unit, and the rank
    is the best position of any of them.
    """
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


def build_outcomes(items: list[dict], index: Any, *, top_k: int) -> tuple[list[dict], list[int]]:
    """Rank every positive item in both lanes; return (outcomes, unmatched ids)."""
    units = gold_units_by_section(list(index.chunks))
    outcomes: list[dict] = []
    unmatched: list[int] = []
    for position, item in enumerate(items):
        if item["expect"] != "answer":
            continue
        key = (item["class_level"], item["subject"], (item.get("section") or "").strip())
        gold = units.get(key, set())
        if not gold:
            unmatched.append(position)
            continue
        filtered = index.search(
            item["question"],
            class_level=item["class_level"],
            subject=item["subject"],
            top_k=top_k,
        )
        unfiltered = index.search(item["question"], top_k=top_k)
        outcomes.append(
            {
                "item_index": position,
                "class_level": item["class_level"],
                "subject": item["subject"],
                "stratum": item["stratum"],
                "split": item["split"],
                "rank_filtered": rank_of(filtered, gold),
                "rank_unfiltered": rank_of(unfiltered, gold),
            }
        )
    return outcomes, unmatched


def _error_analysis(outcomes: list[dict]) -> dict[str, list[int]]:
    """Item indices whose gold unit was not retrieved in the top-k, by stratum.

    Indices point into ``items`` of the golden file, so a reviewer can open
    the exact item; the questions themselves stay out of this artifact.
    """
    misses: dict[str, list[int]] = {}
    for row in outcomes:
        if row["rank_filtered"] == 0:
            misses.setdefault(row["stratum"], []).append(row["item_index"])
    return {stratum: sorted(ids) for stratum, ids in sorted(misses.items())}


def build_report(
    *,
    golden_path: Path,
    corpus_dir: Path | None,
    split: str,
    top_k: int,
    seed: int,
) -> dict:
    from bangla_gpt_api.data.loader import load_sample_corpus
    from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
    from bangla_gpt_api.evaluation.retrieval_strata import (
        BOOTSTRAP_RESAMPLES,
        PRIMARY_METRIC,
        metrics_block,
        strata_report,
    )
    from bangla_gpt_api.retrieval.embedding import build_embedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
    from bangla_gpt_api.services.trace_meta import index_fingerprint

    if corpus_dir is not None:
        chunks = load_nctb_corpus(
            corpus_dir / "normalized",
            quality_report_path=corpus_dir / "quality_report.json",
            multi_class_fallback=True,
        )
        corpus_label = f"nctb:{corpus_dir.name}"
    else:
        chunks = load_sample_corpus()
        corpus_label = "sample_nctb"
    if not chunks:
        raise SystemExit("NO_INDEXABLE_CHUNKS -- build the corpus or drop --corpus-dir")

    from bangla_gpt_api.config import Settings

    index = HybridIndex(chunks, build_embedder(Settings(env="test")))
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    items = data["items"]
    selected = items if split == "all" else [i for i in items if i["split"] == split]
    outcomes, unmatched = build_outcomes(selected, index, top_k=top_k)

    filtered_ranks = [int(row["rank_filtered"]) for row in outcomes]
    unfiltered_ranks = [int(row["rank_unfiltered"]) for row in outcomes]
    filtered_block = metrics_block(filtered_ranks, seed=seed)
    unfiltered_block = metrics_block(unfiltered_ranks, seed=seed)

    from bangla_gpt_api.evaluation.retrieval_strata import metrics_from_ranks, paired_mde

    primary_filtered, _ = metrics_from_ranks(filtered_ranks)
    primary_unfiltered, _ = metrics_from_ranks(unfiltered_ranks)

    return {
        "generated_by": "scripts/strata_report.py",
        "primary_metric": PRIMARY_METRIC,
        "run_conditions": {
            "split": split,
            "corpus": corpus_label,
            "corpus_fingerprint": index_fingerprint(index),
            "golden_file": golden_path.name,
            "golden_dataset_hash": data.get("dataset_hash"),
            "golden_test_split_hash": data.get("test_split_hash"),
            "seed": seed,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "top_k": top_k,
            "positive_items": len(outcomes),
            "negative_items_in_split": sum(1 for i in selected if i["expect"] == "refuse"),
            "gold_unmatched_items": len(unmatched),
        },
        "overall": {
            "filtered": filtered_block,
            "unfiltered": unfiltered_block,
            "filtered_vs_unfiltered_mde": paired_mde(
                primary_filtered[PRIMARY_METRIC], primary_unfiltered[PRIMARY_METRIC]
            ),
        },
        "strata": strata_report(outcomes, keys=STRATA_KEYS, seed=seed),
        "error_analysis": {
            "gold_unmatched_item_indices": unmatched,
            "filtered_misses_by_stratum": _error_analysis(outcomes),
        },
        "notes": (
            "Metrics are macro-averaged over items per stratum; CIs are percentile "
            "bootstrap intervals of the mean (seeded, so they reproduce); "
            "mde_absolute is the smallest absolute change this stratum's n can "
            "detect at 95% CI / 80% power for the primary metric; "
            "filtered_vs_unfiltered_mde is the paired MDE for the filter's effect. "
            "Negative (must-refuse) items are not retrieval metrics -- their "
            "abstention behaviour is measured in the generation report."
        ),
    }


def markdown_summary(report: dict) -> str:
    """A markdown table block for docs; generated, never hand-copied."""
    lines = [
        "| Stratum | n | Recall@1 (CI95) | Recall@5 (CI95) | MRR@10 | nDCG@10 | MDE abs. r@5 / r@1 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    overall = report["overall"]["filtered"]
    lines.append(
        f"| all (filtered) | {overall['n']} | {overall['recall_at_1']} "
        f"({overall['recall_at_1_ci95'][0]}-{overall['recall_at_1_ci95'][1]}) | "
        f"{overall['recall_at_5']} ({overall['recall_at_5_ci95'][0]}-"
        f"{overall['recall_at_5_ci95'][1]}) | {overall['mrr_at_10']} | "
        f"{overall['ndcg_at_10']} | {overall['mde_absolute']} / "
        f"{overall['mde_by_metric']['recall_at_1']} |"
    )
    for value, blocks in report["strata"]["class_level"].items():
        block = blocks["filtered"]
        lines.append(
            f"| class {value} | {block['n']} | {block['recall_at_1']} "
            f"({block['recall_at_1_ci95'][0]}-{block['recall_at_1_ci95'][1]}) | "
            f"{block['recall_at_5']} ({block['recall_at_5_ci95'][0]}-"
            f"{block['recall_at_5_ci95'][1]}) | {block['mrr_at_10']} | "
            f"{block['ndcg_at_10']} | {block['mde_absolute']} / "
            f"{block['mde_by_metric']['recall_at_1']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A8-03 stratified retrieval metrics")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--split", choices=["all", "dev", "test"], default="all")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    report = build_report(
        golden_path=args.golden,
        corpus_dir=args.corpus_dir,
        split=args.split,
        top_k=args.top_k,
        seed=args.seed,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    conditions = report["run_conditions"]
    print(
        f"corpus={conditions['corpus']} ({conditions['corpus_fingerprint']}) "
        f"positives={conditions['positive_items']} "
        f"gold_unmatched={conditions['gold_unmatched_items']} "
        f"split={conditions['split']}"
    )
    print(markdown_summary(report))
    print(f"\nwritten -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
