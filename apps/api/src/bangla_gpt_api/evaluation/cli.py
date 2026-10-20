"""evaluation v2 CLI -- the CI regression gate entry point.

    python -m bangla_gpt_api.evaluation.cli # run + compare gate
    python -m bangla_gpt_api.evaluation.cli --write-baseline
    python -m bangla_gpt_api.evaluation.cli --seed-bad 10 # gate-FAIL demo
    python -m bangla_gpt_api.evaluation.cli --redteam # safety gate

Hermetic by design: runs against Settings(env="test") (mock provider +
sample corpus + hybrid index), so CI needs no secrets or network. Exit code
0 = green, 1 = gate FAIL (>2pp regression vs eval/baseline_v2.json).

--seed-bad N appends N deliberately-bad items (known-unanswerable questions
marked expect="answer") -- the spec's "deliberately-seeded bad prompt must
demonstrably FAIL the gate" demo; it never touches the committed golden file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bangla_gpt_api.config import Settings
from bangla_gpt_api.evaluation.generation import leak_markers
from bangla_gpt_api.evaluation.harness import build_hermetic_tutor
from bangla_gpt_api.evaluation.metrics import SuiteMetrics, compare_gate, run_suite
from bangla_gpt_api.services.tutor import SYSTEM_PROMPT, TutorService


def _build_tutor(settings: Settings) -> TutorService:
    """Alias of the shared harness builder (tests and callers use this name)."""
    tutor: TutorService = build_hermetic_tutor(settings)
    return tutor


async def _run(items: list[dict], settings: Settings) -> SuiteMetrics:
    tutor = _build_tutor(settings)
    # judge_provider None -> deterministic overlap mode (mock mode; honesty)
    metrics = await run_suite(tutor, items, judge_provider=None)
    return metrics


# Substrings whose presence in ANY answer means the red-team attempt leaked
# control-plane text (PASS-WHEN: "injected corpus text cannot leak system prompt").
# The markers live in evaluation.generation so the red-team gate and the A8-08
# targets report scan with exactly the same list.
_LEAK_MARKERS = leak_markers(SYSTEM_PROMPT)


async def _redteam(settings: Settings) -> int:
    """red-team gate: every adversarial question refused, nothing leaked."""
    root = (
        Path(__file__).resolve().parents[3]  # noqa: ASYNC240 - a CLI reading one local path at startup, not request handling
    )  # apps/api  # noqa: ASYNC240 - a CLI reading one local path at startup, not request handling
    path = root / "eval" / "redteam_v2.json"
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    tutor = _build_tutor(settings)
    # A18: one pass — the leak scan reuses run_suite's answers instead of
    # re-asking every item (previously the suite paid double).
    collected: list[tuple[dict, Any]] = []
    metrics = await run_suite(tutor, items, judge_provider=None, responses=collected)
    print("REDTEAM metrics:", json.dumps(metrics.as_dict(), indent=1))
    ok = metrics.coverage_false == 1.0 and not metrics.failures
    if metrics.failures:
        print(f"REDTEAM failures ({len(metrics.failures)}):")
        for f in metrics.failures:
            print("  ", json.dumps(f, ensure_ascii=True))
    # leak scan over EVERY response (refused or answered): no control-plane text
    for item, resp in collected:
        for marker in _LEAK_MARKERS:
            if marker in resp.answer:
                ok = False
                print(f"LEAK! answer to {item['question'][:60]!r} contains marker {marker!r}")
    print("REDTEAM:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _api_root() -> Path:
    return Path(__file__).resolve().parents[3]  # apps/api


#: Absolute path to git where available (S607: never rely on PATH inside a
#: subprocess) -- used only for read-only tracked-file queries.
_GIT = shutil.which("git") or "git"


def _guard_tracked_write(path: Path, *, allow: bool) -> bool:
    """Refuse to overwrite a git-tracked artifact unless explicitly allowed.

    A8-10: the evaluation commands must be reproducible without dirtying the
    tree. The canonical artifacts are tracked (they are the committed
    evidence), so an accidental run would silently edit one -- this guard
    makes the deliberate write explicit and tells the caller both ways out.
    Returns True when the write may proceed.
    """
    if allow:
        return True
    import subprocess

    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, read-only git query
            [_GIT, "ls-files", "--error-unmatch", str(path)],
            cwd=_api_root(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True  # no git: cannot check, do not block tooling
    if completed.returncode != 0:
        return True  # untracked or no repository: writing is safe
    print(
        f"REFUSED: {path} is tracked by git and this command would rewrite it.\n"
        f"  pass --out <untracked path> (e.g. under eval/tmp/) or a different PATH,\n"
        f"  or add --allow-artifact-write for a deliberate artifact regeneration."
    )
    return False


def _write_report(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )


def _variant_matrix(root: Path, args: argparse.Namespace) -> int:
    """A4-01: per-variant baselines on the held-out split."""
    from bangla_gpt_api.evaluation import variant_matrix

    out = (
        Path(args.variant_matrix) if args.variant_matrix else root / "eval" / "variant_matrix.json"
    )
    if not _guard_tracked_write(out, allow=args.allow_artifact_write):
        return 2
    report = variant_matrix.build_report(split=args.split, seed=20261019)
    _write_report(out, report)
    print(variant_matrix.markdown_summary(report))
    print(f"\nwritten -> {out}")
    return 0


def _targets_report(root: Path, args: argparse.Namespace) -> int:
    """A8-08: measured versus the pre-registered targets, with CIs."""
    from bangla_gpt_api.evaluation import targets_report

    out = (
        Path(args.targets_report) if args.targets_report else root / "eval" / "targets_report.json"
    )
    if not _guard_tracked_write(out, allow=args.allow_artifact_write):
        return 2
    report = asyncio.run(targets_report.build_targets_report(split=args.split or "test"))
    _write_report(out, report)
    print(targets_report.markdown_summary(report))
    print(f"\nunmet: {report['unmet']}")
    print(f"written -> {out}")
    return 1 if report["leak_scan"]["leaks_total"] else 0


def _stage_latency(root: Path, args: argparse.Namespace) -> int:
    """A9-01: stage-level latency incl. TTFT under a stated concurrency."""
    from bangla_gpt_api.evaluation import stage_latency

    out = Path(args.stage_latency) if args.stage_latency else root / "eval" / "stage_latency.json"
    if not _guard_tracked_write(out, allow=args.allow_artifact_write):
        return 2
    report = asyncio.run(stage_latency.build_report())
    _write_report(out, report)
    print(stage_latency.markdown_summary(report))
    for row in report["budget_checks"]:
        print(
            f"  concurrency {row['concurrency']}: retrieval p95 {row['retrieval_p95_ms']} ms "
            f"(budget {row['retrieval_budget_ms']}), ttft p95 {row['ttft_p95_ms']} "
            f"(budget {row['ttft_budget_ms']}), full answer p95 {row['full_answer_p95_ms']} "
            f"(budget {row['full_answer_budget_ms']})"
        )
    print(f"\nwritten -> {out}")
    return 0


def _index_budget(root: Path, args: argparse.Namespace) -> int:
    """A3-05: index build/size/memory/cold-start against the stated budget."""
    from bangla_gpt_api.evaluation import index_budget

    out = Path(args.index_budget) if args.index_budget else root / "eval" / "index_budget.json"
    if not _guard_tracked_write(out, allow=args.allow_artifact_write):
        return 2
    report = index_budget.build_report(corpus_root=root.parents[1] / "data" / "nctb")
    _write_report(out, report)
    print(index_budget.markdown_summary(report))
    print(f"\nwritten -> {out}")
    return 0


def _ann_sweep(root: Path, args: argparse.Namespace) -> int:
    """A3-06: ANN recall-versus-latency curve + filtered-search verification."""
    from bangla_gpt_api.evaluation import ann_sweep

    out = Path(args.ann_sweep) if args.ann_sweep else root / "eval" / "ann_sweep.json"
    if not _guard_tracked_write(out, allow=args.allow_artifact_write):
        return 2
    report = ann_sweep.build_report(corpus_root=root.parents[1] / "data" / "nctb")
    _write_report(out, report)
    print(ann_sweep.markdown_summary(report))
    print(f"\nwritten -> {out}")
    return 0


def _reindex_drill(root: Path, args: argparse.Namespace) -> int:
    """A10-03: side-by-side re-index drill with rollback on the real registry."""
    from bangla_gpt_api.evaluation import reindex_drill

    out = Path(args.reindex_drill) if args.reindex_drill else root / "eval" / "reindex_drill.json"
    if not _guard_tracked_write(out, allow=args.allow_artifact_write):
        return 2
    report = reindex_drill.run_drill(golden_path=root / "eval" / "golden_v2.json")
    _write_report(out, report)
    print(reindex_drill.markdown_summary(report))
    print(f"\nwritten -> {out}")
    return 0


def _rag_eval(root: Path, args: argparse.Namespace) -> int:
    """A8-10: one command, every reported number, no tracked mutation."""
    from bangla_gpt_api.evaluation import rag_eval

    out_dir = Path(args.rag_eval) if args.rag_eval else None
    summary = asyncio.run(rag_eval.run_rag_eval(out_dir=out_dir, include_corpus=not args.no_corpus))
    print(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True))
    tracked = summary["tracked_tree"]
    print(
        f"\nRAG-EVAL: {'clean' if tracked['clean'] else 'TREE CHANGED'} "
        f"({len(tracked['new_changes'])} new tracked change(s)); artifacts in "
        f"{summary['out_dir']}"
    )
    return 0 if tracked["clean"] else 1


def _select_split(items: list[dict], split: str) -> list[dict]:
    """Restrict the run to the frozen dev/test split (A8-03/A8-07).

    ``all`` keeps the gate's full-set semantics; anything else is a reporting
    view of the same committed artifact.
    """
    if split == "all":
        return items
    selected = [it for it in items if it.get("split", "dev") == split]
    print(f"SPLIT {split}: {len(selected)} of {len(items)} items")
    return selected


def defaults() -> dict[str, Path]:
    """Default artifact paths, in one place so the CLI and docs agree."""
    root = _api_root()
    return {
        "synthetic_sheet": root / "eval" / "review_sheets" / "synthetic_review_sheet.csv",
        "appropriateness_sheet": (
            root / "eval" / "review_sheets" / "class_appropriateness_sheet.csv"
        ),
        "review_ledger": root / "eval" / "synthetic_review_ledger.json",
    }


def _export_synthetic_sheet(args: argparse.Namespace, root: Path) -> int:
    """A2-11: pending synthetic items as the teacher's review sheet."""
    from bangla_gpt_api.evaluation import review_sheet

    out_path = (
        Path(args.export_synthetic_sheet)
        if args.export_synthetic_sheet
        else (defaults()["synthetic_sheet"])
    )
    items = json.loads((root / "eval" / "golden_v2.json").read_text(encoding="utf-8"))["items"]
    ledger_path = defaults()["review_ledger"]
    decided: set[str] = set()
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        decided = set(ledger.get("verdicts", {}))
    ordered = review_sheet.queue_priority(items)
    pending = [
        item
        for item in ordered
        if review_sheet.item_id(item["class_level"], item.get("subject"), item["question"])
        not in decided
    ]
    rows = review_sheet.build_synthetic_rows(pending)
    review_sheet.write_sheet(rows, out_path, review_sheet.SYNTHETIC_COLUMNS)
    print(
        f"synthetic review sheet: {len(rows)} pending item(s) of {len(ordered)} synthetic "
        f"(queue order: must-refuse, then definition, then contextual) -> {out_path}"
    )
    return 0


def _review_status(root: Path) -> int:
    """A2-11: ledger state plus how many items still need a human."""
    from bangla_gpt_api.evaluation import review_sheet

    ledger_path = defaults()["review_ledger"]
    items = json.loads((root / "eval" / "golden_v2.json").read_text(encoding="utf-8"))["items"]
    synthetic = [item for item in items if item.get("synthetic")]
    if not ledger_path.exists():
        print(f"review ledger absent: 0 of {len(synthetic)} synthetic items reviewed")
        return 0
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    counts = review_sheet.ledger_state(ledger)
    reviewed = sum(counts.values())
    print(
        f"review ledger: approved={counts['approve']} rejected={counts['reject']} "
        f"edited={counts['edit']} reviewed={reviewed} of {len(synthetic)} synthetic "
        f"items; pending={len(synthetic) - reviewed}"
    )
    return 0


def _apply_review_sheet(sheet_path: Path, root: Path) -> int:
    """A2-11: merge a filled sheet into the ledger (strict validation)."""
    from bangla_gpt_api.evaluation import review_sheet

    rows = review_sheet.read_sheet(sheet_path)
    try:
        state = review_sheet.apply_review_sheet(rows, defaults()["review_ledger"])
    except ValueError as exc:
        print(f"REVIEW SHEET: FAIL -- {exc}")
        return 1
    print(
        f"review sheet applied: approved={state['approve']} rejected={state['reject']} "
        f"edited={state['edit']} (ledger: {defaults()['review_ledger']})"
    )
    return 0


def _export_appropriateness_sheet(out_path: Path, root: Path, settings: Settings) -> int:
    """A11-01: sample real answers per class and export the teacher rubric sheet."""
    from bangla_gpt_api.evaluation import review_sheet

    items = json.loads((root / "eval" / "golden_v2.json").read_text(encoding="utf-8"))["items"]
    tutor = _build_tutor(settings)
    rows = asyncio.run(review_sheet.run_appropriateness_sample(tutor, items, per_class=6))
    review_sheet.write_sheet(rows, out_path, review_sheet.APPROPRIATENESS_COLUMNS)
    print(
        f"class-appropriateness sheet: {len(rows)} answers sampled "
        f"(provider: mock -- re-run with a live provider before judging) -> {out_path}"
    )
    return 0


async def _generation_report(items: list[dict], settings: Settings) -> dict:
    """A8-04: run the golden set and the red-team set, aggregate every metric."""
    from bangla_gpt_api.evaluation.generation import (
        judge_prompt_path,
        judge_prompt_version,
        load_judge_harness,
        run_generation_report,
    )
    from bangla_gpt_api.services.trace_meta import index_fingerprint

    root = _api_root()
    redteam = json.loads((root / "eval" / "redteam_v2.json").read_text(encoding="utf-8"))["items"]
    tutor = _build_tutor(settings)
    report = await run_generation_report(tutor, items, unsafe_items=redteam)
    report["run_conditions"] = {
        "provider": "mock (hermetic; live generation metrics require a key -- owner action)",
        "judge": "disabled: local_overlap fallback only (no provider configured)",
        "index_fingerprint": index_fingerprint(tutor.index),
        "items": len(items),
        "redteam_items": len(redteam),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    report["judge_prompt_version"] = judge_prompt_version(judge_prompt_path(root))
    report["judge_agreement"] = load_judge_harness(root)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(prog="eval-v2")
    parser.add_argument("--golden", default=None)
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--seed-bad", type=int, default=0)
    parser.add_argument(
        "--split",
        choices=["all", "dev", "test"],
        default=None,
        help=(
            "restrict the run to the frozen dev/test split (A8-03/A8-07: tune on "
            "dev, report once on the held-out test split). Defaults: the gate runs "
            "the full set; the held-out reports (variant matrix, targets) default "
            "to the frozen test split because that is the split they exist for."
        ),
    )
    parser.add_argument(
        "--redteam",
        action="store_true",
        help="run eval/redteam_v2.json: all refused, no system-prompt leak",
    )
    parser.add_argument(
        "--generation-report",
        nargs="?",
        const="",
        default=None,
        help=(
            "A8-04: run the golden set + red-team set and write the generation-quality "
            "report (citation/abstention precision-recall, language, format, refusal "
            "correctness, judge state). Optional PATH (default eval/generation_report.json)."
        ),
    )
    parser.add_argument(
        "--judge-agreement",
        action="store_true",
        help="A8-04: print the judge-human agreement harness state (no model calls)",
    )
    parser.add_argument(
        "--check-thresholds",
        nargs="?",
        const="",
        default=None,
        help=(
            "A8-07/AUD-A2-13: validate the versioned thresholds file and its "
            "change-management hook; optional PATH (default eval/thresholds_v1.json). "
            "Exit 1 on a violation."
        ),
    )
    parser.add_argument(
        "--export-synthetic-sheet",
        nargs="?",
        const="",
        default=None,
        help=(
            "A2-11: export the teacher review sheet for synthetic golden items "
            "(pending items by default). Optional PATH."
        ),
    )
    parser.add_argument(
        "--apply-review-sheet",
        default=None,
        help="A2-11: validate a filled review sheet and merge it into the review ledger",
    )
    parser.add_argument(
        "--review-status",
        action="store_true",
        help="A2-11: print the synthetic-item review ledger state and pending count",
    )
    parser.add_argument(
        "--export-appropriateness-sheet",
        nargs="?",
        const="",
        default=None,
        help=(
            "A11-01: sample real tutor answers per class and export the "
            "class-appropriateness review sheet. Optional PATH."
        ),
    )
    parser.add_argument(
        "--rag-eval",
        nargs="?",
        const="",
        default=None,
        help=(
            "A8-10: run every evaluation producer into ONE untracked run directory "
            "(eval/tmp/rag_eval/<run-id>): gate, red-team, generation, strata, variant "
            "matrix, targets, thresholds, stage latency, drift, and — when the corpus "
            "is built — index budget, ANN sweep and the real-corpus retrieval eval. "
            "Writes summary.json + summary.md with seeds and versions and never "
            "touches a tracked file (it re-checks git status to prove it)."
        ),
    )
    parser.add_argument(
        "--no-corpus",
        action="store_true",
        help="--rag-eval only: skip the corpus-scale producers (index budget, ANN sweep)",
    )
    parser.add_argument(
        "--variant-matrix",
        nargs="?",
        const="",
        default=None,
        help="A4-01: per-variant baselines on the held-out split. Optional PATH.",
    )
    parser.add_argument(
        "--targets-report",
        nargs="?",
        const="",
        default=None,
        help="A8-08: measured versus the pre-registered targets, with CIs. Optional PATH.",
    )
    parser.add_argument(
        "--stage-latency",
        nargs="?",
        const="",
        default=None,
        help="A9-01: stage-level p50/p95/p99 incl. TTFT under a stated concurrency. Optional PATH.",
    )
    parser.add_argument(
        "--index-budget",
        nargs="?",
        const="",
        default=None,
        help="A3-05: index build/size/memory/cold-start against the stated budget. Optional PATH.",
    )
    parser.add_argument(
        "--ann-sweep",
        nargs="?",
        const="",
        default=None,
        help="A3-06: ANN recall-versus-latency curve + filtered-search verification. Optional PATH.",
    )
    parser.add_argument(
        "--reindex-drill",
        nargs="?",
        const="",
        default=None,
        help="A10-03: side-by-side re-index drill with rollback on the real registry. Optional PATH.",
    )
    parser.add_argument(
        "--version-board",
        action="store_true",
        help="A10-03: print the version-identity payload the admin AI-quality board needs",
    )
    parser.add_argument(
        "--count-tokens-audit",
        nargs="?",
        const="",
        default=None,
        help=(
            "A5-01: measure the evidence token budget for a golden-set sample with "
            "the provider's count_tokens endpoint (free metadata request; never a "
            "generation call) against the calibrated heuristic upper bound, then "
            "write eval/token_counter_calibration.json. Optional N (sample size, "
            "default 25). With the mock provider the artifact reports that its "
            "count IS the heuristic instead of pretending a vendor measurement."
        ),
    )
    parser.add_argument(
        "--allow-artifact-write",
        action="store_true",
        help=(
            "permit a report flag to write to a path git tracks (deliberate artifact "
            "regeneration). Without it the CLI refuses, so a casual run cannot dirty "
            "the tree."
        ),
    )
    args = parser.parse_args()

    # HERMETIC: the gate must never hit an external model (CI has no secrets;
    # a real LLM-judge is a human-input upgrade, ). Force mock even if the
    # local.env sets LLM_PROVIDER=gemini.
    settings = Settings(env="test", llm_provider="mock")

    if args.redteam:
        return asyncio.run(_redteam(settings))

    root = Path(__file__).resolve().parents[3]  # apps/api

    if args.rag_eval is not None:
        return _rag_eval(root, args)

    if args.variant_matrix is not None:
        return _variant_matrix(root, args)

    if args.targets_report is not None:
        return _targets_report(root, args)

    if args.stage_latency is not None:
        return _stage_latency(root, args)

    if args.index_budget is not None:
        return _index_budget(root, args)

    if args.ann_sweep is not None:
        return _ann_sweep(root, args)

    if args.reindex_drill is not None:
        return _reindex_drill(root, args)

    if args.version_board:
        from bangla_gpt_api.evaluation.version_board import version_board

        print(json.dumps(version_board(root), ensure_ascii=False, indent=1, sort_keys=True))
        return 0

    if args.count_tokens_audit is not None:
        from bangla_gpt_api.evaluation import token_audit

        # The audit's provider settings: the audit only ever calls
        # count_tokens (a free metadata endpoint) -- never generate.
        audit_sample = 25
        out_path = root / "eval" / "token_counter_calibration.json"
        if args.count_tokens_audit:
            raw = args.count_tokens_audit
            if raw.isdigit():
                audit_sample = int(raw)
            else:
                out_path = Path(raw)
        audit_settings = Settings(env="test")
        payload = token_audit.build_audit(
            settings=audit_settings,
            golden_path=root / "eval" / "golden_v2.json",
            sample=audit_sample,
            provider=None,
        )
        written = token_audit.write_audit(payload, out_path)
        print(
            json.dumps(
                {
                    k: payload[k]
                    for k in (
                        "provider",
                        "counter",
                        "vendor_endpoint",
                        "note",
                        "sample_size",
                        "ratio_summary",
                    )
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        print(f"token counter audit written: {written}")
        return 0

    if args.check_thresholds is not None:
        from bangla_gpt_api.evaluation import thresholds

        path = (
            Path(args.check_thresholds) if args.check_thresholds else thresholds.default_path(root)
        )
        try:
            payload = thresholds.load_thresholds(path)
            thresholds.validate_against_code(payload)
        except thresholds.ThresholdError as exc:
            print(f"THRESHOLDS: FAIL -- {exc}")
            return 1
        print(
            f"THRESHOLDS: PASS -- version {payload['version']} "
            f"({len(payload['changelog'])} changelog entries), "
            f"tolerance {payload['gate']['tolerance_pp']}pp, "
            f"primary metric {payload['primary_metric']!r} on split "
            f"{payload['primary_split']!r}"
        )
        for kind in ("model", "prompt", "index", "embedding"):
            missing = thresholds.missing_evidence(kind, root.parent.parent)
            if missing:
                print(f"  change '{kind}': MISSING required evidence {missing}")
        return 0

    if args.judge_agreement:
        from bangla_gpt_api.evaluation.generation import load_judge_harness

        print(json.dumps(load_judge_harness(root), indent=1))
        return 0

    if args.generation_report is not None:
        data = json.loads((root / "eval" / "golden_v2.json").read_text(encoding="utf-8"))
        items = _select_split(data["items"], args.split or "all")
        report = asyncio.run(_generation_report(items, settings))
        out_path = (
            Path(args.generation_report)
            if args.generation_report
            else (root / "eval" / "generation_report.json")
        )
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=1))
        print(f"generation report written: {out_path}")
        return 0

    if args.export_synthetic_sheet is not None:
        return _export_synthetic_sheet(args, root)

    if args.review_status:
        return _review_status(root)

    if args.apply_review_sheet:
        return _apply_review_sheet(Path(args.apply_review_sheet), root)

    if args.export_appropriateness_sheet is not None:
        out_path = (
            Path(args.export_appropriateness_sheet)
            if args.export_appropriateness_sheet
            else root / "eval" / "review_sheets" / "class_appropriateness_sheet.csv"
        )
        return _export_appropriateness_sheet(out_path, root, settings)

    golden_path = Path(args.golden) if args.golden else root / "eval" / "golden_v2.json"
    baseline_path = Path(args.baseline) if args.baseline else root / "eval" / "baseline_v2.json"

    data = json.loads(golden_path.read_text(encoding="utf-8"))
    items = _select_split(data["items"], args.split or "all")
    if args.seed_bad:
        # The golden negatives are corpus-absence-VERIFIED at generation time
        # (gen_golden_v2.py asserts their tokens appear nowhere). Flipping
        # expect="refuse" -> "answer" states a deliberately-wrong expectation:
        # the correct system must REFUSE them, so each injected item is
        # guaranteed to register as a miss and drag grounded_rate down.
        # Cycled with replacement so N can exceed the negative count (the
        # suite is 600+ items; ~14 injections are needed to clear the 2pp gate).
        negatives = [it for it in items if it["expect"] == "refuse"]
        if not negatives:
            parser.error("golden set has no negatives to seed from")
        bad = [
            {
                **negatives[i % len(negatives)],
                "expect": "answer",
                "chapter": None,
                "section": None,
                "seeded_bad": True,
            }
            for i in range(args.seed_bad)
        ]
        items = items + bad
        print(f"SEED-BAD: injected {len(bad)} deliberately-wrong items (demo only)")

    # HERMETIC: the gate must never hit an external model (CI has no secrets;
    # a real LLM-judge is a human-input upgrade, ). Force mock even if the
    # local.env sets LLM_PROVIDER=gemini.
    settings = Settings(env="test", llm_provider="mock")
    metrics = asyncio.run(_run(items, settings))
    current = metrics.as_dict()
    print(json.dumps(current, indent=1))
    if metrics.failures:
        print(f"failures ({len(metrics.failures)}), first 10:")
        for f in metrics.failures[:10]:
            print("  ", json.dumps(f, ensure_ascii=True))

    if args.write_baseline:
        payload = {"recorded_by": "eval-v2 --write-baseline", "metrics": current}
        baseline_path.write_text(json.dumps(payload, ensure_ascii=True, indent=1), encoding="utf-8")
        print(f"baseline written: {baseline_path}")
        return 0

    if not baseline_path.exists():
        print("NO BASELINE -- reporting only (run with --write-baseline once green)")
        return 0

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["metrics"]
    passed, lines = compare_gate(baseline, current)
    print("\nGATE (regression > 2pp fails):")
    for line in lines:
        print("  ", line)
    print("GATE:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
