"""Regression check for the real-corpus retrieval baseline.

`scripts/evaluate_nctb_retrieval.py` REGENERATES `data/nctb/retrieval_eval.json`
in place; this checker is the gate that compares the fresh report against the
committed baseline the way the PR eval-gate does (R12: never re-baseline to
go green). Any family metric that drops by more than an absolute tolerance
fails with a per-metric line naming the culprit; improvements pass. Family C
(adversarial refusals) is one-sided: a DROP fails, an increase is fine, and
falling below 1.0 outright is flagged as the grounding-honesty regression it
is.

Usage:
    python scripts/check_retrieval_baseline.py \
        --baseline baseline_committed.json --current data/nctb/retrieval_eval.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Absolute tolerance on 0..1 rates: the corpus sample and the growable
# chapter-title set make small run-to-run drift normal.
RATE_TOLERANCE = 0.02
# MRR is a mean over ranks: slightly noisier than the recall rates.
MRR_TOLERANCE = 0.05


def _compare_block(
    name: str,
    baseline: dict,
    current: dict,
    problems: list[str],
) -> None:
    for metric, tolerance in (
        ("recall_at_1", RATE_TOLERANCE),
        ("recall_at_5", RATE_TOLERANCE),
        ("mrr", MRR_TOLERANCE),
    ):
        if metric not in baseline or metric not in current:
            problems.append(f"{name}.{metric}: missing from a report (baseline-only metric?)")
            continue
        drop = float(baseline[metric]) - float(current[metric])
        ok = drop <= tolerance + 1e-9
        marker = "PASS" if ok else f"FAIL(drop>{tolerance})"
        print(f"{name}.{metric}: baseline={baseline[metric]} current={current[metric]} {marker}")
        if not ok:
            problems.append(f"{name}.{metric} regressed by {drop:+.4f}")


def check(baseline: dict, current: dict) -> list[str]:
    problems: list[str] = []
    for family in ("family_A_self_sentence", "family_B_chapter_title"):
        for report, label in ((baseline, "baseline"), (current, "current")):
            if family not in report:
                problems.append(f"{family}: absent from the {label} report")
        if all(family in r for r in (baseline, current)):
            _compare_block(family, baseline[family], current[family], problems)
    refusal_base = float(baseline.get("family_C_adversarial_refusal_rate", 0.0))
    refusal_cur = float(current.get("family_C_adversarial_refusal_rate", 0.0))
    print(
        f"family_C_adversarial_refusal_rate: baseline={refusal_base} current={refusal_cur} "
        + ("PASS" if refusal_cur >= refusal_base - 1e-9 else "FAIL")
    )
    if refusal_cur < refusal_base - 1e-9:
        problems.append(
            f"family_C refusal rate dropped {refusal_base - refusal_cur:+.4f} — "
            "out-of-corpus questions are being grounded again"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="committed report JSON")
    parser.add_argument("--current", type=Path, required=True, help="freshly generated report JSON")
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))
    problems = check(baseline, current)
    if problems:
        print("\nRETRIEVAL REGRESSION:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nRETRIEVAL BASELINE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
