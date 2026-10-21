"""A8-10: one command that reproduces every reported number, hermetically.

The audit's A8-10 status was PARTIAL: a gate existed, but no single command
wrote the whole evaluation picture, no markdown summary carried seeds and
versions, and the sibling retrieval script overwrote a *tracked* artifact
with machine-specific latency values.

``run_rag_eval`` is that command's engine. It runs every evaluation artifact
producer this package owns into one output directory that is **untracked by
construction** (``apps/api/eval/tmp/`` is ignored by the repository's ``tmp/``
rule, verified with ``git check-ignore``), writes one JSON per producer plus a
``summary.md`` carrying the seeds, versions and the head of each artifact, and
finishes by re-reading ``git status`` to state whether it touched any tracked
file (it also records a pre-run status, so a dirty tree is attributed
correctly instead of blamed on the run).

The producers write their *canonical* artifacts (``eval/strata_report.json``
etc.) only when invoked directly for a deliberate regeneration; this command
always redirects to its own directory, so running it can never dirty the tree.
"""

from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Absolute path to git where available; the read-only status queries below
#: must not depend on PATH resolution inside a subprocess (S607).
_GIT = shutil.which("git") or "git"

#: Output root for every run: under ``eval/tmp/`` which the repository's
#: ``tmp/`` gitignore rule excludes (asserted by a test with ``git
#: check-ignore`` so the safety property cannot silently regress).
DEFAULT_RUN_ROOT = Path(__file__).resolve().parents[3] / "eval" / "tmp" / "rag_eval"


def _git_status(repo_root: Path) -> list[str]:
    """Tracked-file changes as ``git status --porcelain`` sees them (read-only)."""
    try:
        completed = subprocess.run(  # noqa: S603,S607 - fixed argv, read-only git query
            [_GIT, "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ["<git unavailable>"]
    if completed.returncode != 0:
        return ["<not a git checkout>"]
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _git_sha(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603,S607 - fixed argv, read-only git query
            [_GIT, "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None if completed.returncode == 0 else None


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in ("fastapi", "pydantic", "pydantic-settings", "httpx", "sqlalchemy", "pytest"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def versions_block(api_root: Path) -> dict[str, Any]:
    """The seeds-and-versions block every run summary must carry."""
    from bangla_gpt_api.services.tutor import PROMPT_VERSION

    golden_path = api_root / "eval" / "golden_v2.json"
    golden: dict[str, Any] = {"file": golden_path.name}
    if golden_path.is_file():
        payload = json.loads(golden_path.read_text(encoding="utf-8"))
        golden |= {
            "dataset_hash": payload.get("dataset_hash"),
            "test_split_hash": payload.get("test_split_hash"),
            "items": len(payload.get("items", [])),
        }
    return {
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()} / {platform.machine()}",
        "packages": _package_versions(),
        "prompt_version": PROMPT_VERSION,
        "golden": golden,
        "seeds": {
            "variant_matrix": 20261019,
            "strata_report": 20261019,
            "targets_report": 20261019,
            "retrieval_eval": 20260825,
            "ann_sweep": 20261019,
        },
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )


def _artifact_head(path: Path) -> str:
    """A few lines of one artifact, for the markdown summary."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "(unreadable)"
    lines = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True).splitlines()
    return "\n".join(lines[:28])


def _roots() -> tuple[Path, Path]:
    """(apps/api, repository root) resolved synchronously (not on a request path)."""
    api_root = Path(__file__).resolve().parents[3]
    return api_root, api_root.parents[1]


async def run_rag_eval(
    *,
    out_dir: Path | None = None,
    corpus_root: Path | None = None,
    include_corpus: bool = True,
    seed: int = 20261019,
    stage_concurrency: tuple[int, ...] = (1, 8),
    stage_iterations: int = 30,
    golden_path: Path | None = None,
    redteam_path: Path | None = None,
) -> dict[str, Any]:
    """Run every evaluation producer into ``out_dir`` and write ``summary.md``."""
    api_root, repo_root = _roots()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir or (DEFAULT_RUN_ROOT / run_id)
    target.mkdir(parents=True, exist_ok=True)
    status_before = _git_status(repo_root)
    started = time.perf_counter()

    produced: dict[str, Any] = {}

    # 1. Gate: the golden suite against the committed baseline.
    from bangla_gpt_api.evaluation.harness import build_hermetic_tutor, hermetic_settings
    from bangla_gpt_api.evaluation.metrics import compare_gate, run_suite

    tutor = build_hermetic_tutor(hermetic_settings())
    golden_file = golden_path or (api_root / "eval" / "golden_v2.json")
    redteam_file = redteam_path or (api_root / "eval" / "redteam_v2.json")
    golden = json.loads(golden_file.read_text(encoding="utf-8"))
    items = golden["items"]
    metrics = await run_suite(tutor, items, judge_provider=None)
    baseline_path = api_root / "eval" / "baseline_v2.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["metrics"]
    passed, lines = compare_gate(baseline, metrics.as_dict())
    _write_json(
        target / "gate.json",
        {
            "passed": passed,
            "lines": lines,
            "metrics": metrics.as_dict(),
            "failures": len(metrics.failures),
            "baseline": baseline_path.name,
        },
    )
    produced["gate.json"] = {"gate_passed": passed, "metrics": len(lines)}

    # 2. Red-team safety gate (refusals + leak scan).
    from bangla_gpt_api.evaluation.generation import leak_markers
    from bangla_gpt_api.services.tutor import SYSTEM_PROMPT

    redteam_items = json.loads((api_root / "eval" / "redteam_v2.json").read_text(encoding="utf-8"))[
        "items"
    ]
    collected: list[tuple[dict, Any]] = []
    redteam_metrics = await run_suite(
        tutor, redteam_items, judge_provider=None, responses=collected
    )
    markers = leak_markers(SYSTEM_PROMPT)
    leaks = [
        {"item_index": index, "marker": marker}
        for index, (_item, response) in enumerate(collected)
        for marker in markers
        if marker in str(getattr(response, "answer", "") or "")
    ]
    _write_json(
        target / "redteam.json",
        {
            "refused": sum(
                1 for _item, response in collected if not bool(getattr(response, "grounded", False))
            ),
            "total": len(collected),
            "coverage_false": redteam_metrics.coverage_false,
            "leaks": leaks,
            "leak_markers": list(markers),
        },
    )
    produced["redteam.json"] = {"leaks": len(leaks), "total": len(collected)}

    # 3. Generation report (full set + red-team refusal slice).
    from bangla_gpt_api.evaluation.generation import run_generation_report

    rows: list[dict] = []
    generation = await run_generation_report(
        tutor, items, unsafe_items=redteam_items, rows_out=rows
    )
    generation["split_view"] = {
        split: sum(1 for row in rows if row.get("split") == split) for split in ("dev", "test")
    }
    from bangla_gpt_api.services.trace_meta import index_fingerprint

    generation["index_fingerprint"] = index_fingerprint(tutor.index)
    generation["provider"] = "mock (hermetic)"
    _write_json(target / "generation_report.json", generation)
    _write_json(target / "generation_rows.json", rows)
    produced["generation_report.json"] = {
        "items": generation["items"],
        "citation_precision": generation["citation_precision"],
    }

    # 4. Stratified retrieval report via the script (its own JSON writer).
    _run_script(
        api_root,
        "strata_report.py",
        "--out",
        str(target / "strata_report.json"),
        "--seed",
        str(seed),
        "--golden",
        str(golden_file),
    )
    produced["strata_report.json"] = {"script": "scripts/strata_report.py"}

    # 5. Variant matrix on the held-out split.
    from bangla_gpt_api.evaluation import variant_matrix as vm

    variant_report = vm.build_report(golden_path=golden_file, seed=seed, split="test")
    _write_json(target / "variant_matrix.json", variant_report)
    produced["variant_matrix.json"] = vm.markdown_summary(variant_report)

    # 6. Targets versus measured, with CIs.
    from bangla_gpt_api.evaluation import targets_report as tr

    targets = await tr.build_targets_report(
        golden_path=golden_file, redteam_path=redteam_file, seed=seed
    )
    _write_json(target / "targets_report.json", targets)
    produced["targets_report.json"] = tr.markdown_summary(targets)

    # 7. Thresholds register validity + required-evidence state.
    from bangla_gpt_api.evaluation import thresholds as th

    thresholds_payload = th.load_thresholds(th.default_path(api_root))
    th.validate_against_code(thresholds_payload)
    missing = {
        kind: th.missing_evidence(kind, repo_root)
        for kind in ("model", "prompt", "index", "embedding")
    }
    stale = {
        kind: th.stale_evidence(kind, repo_root, [])
        for kind in ("model", "prompt", "index", "embedding")
    }
    _write_json(
        target / "thresholds.json",
        {
            "version": thresholds_payload["version"],
            "primary_metric": thresholds_payload["primary_metric"],
            "primary_split": thresholds_payload["primary_split"],
            "targets": thresholds_payload["targets"],
            "missing_evidence": missing,
            "stale_evidence": stale,
        },
    )
    produced["thresholds.json"] = {"version": thresholds_payload["version"]}

    # 8. Stage-level latency incl. TTFT under a stated concurrency.
    from bangla_gpt_api.evaluation import stage_latency

    stage_report = await stage_latency.build_report(
        concurrency_levels=stage_concurrency, iterations=stage_iterations
    )
    _write_json(target / "stage_latency.json", stage_report)
    produced["stage_latency.json"] = stage_latency.markdown_summary(stage_report)

    # 9. Drift report (query-topic proxy versus corpus coverage and staleness).
    _run_script(
        api_root,
        "drift_report.py",
        "--out",
        str(target / "drift_report.json"),
        "--markdown",
        str(target / "drift_report.md"),
        "--eval",
        str(golden_file),
        "--quiet",
    )
    produced["drift_report.json"] = {"markdown": "drift_report.md"}

    # 10. Corpus-scale producers: only when the corpus artifacts exist.
    corpus = corpus_root or (repo_root / "data" / "nctb")
    corpus_present = (corpus / "normalized").is_dir()
    if include_corpus and corpus_present:
        from bangla_gpt_api.evaluation import ann_sweep, index_budget

        budget = index_budget.build_report(corpus_root=corpus)
        _write_json(target / "index_budget.json", budget)
        produced["index_budget.json"] = index_budget.markdown_summary(budget)

        ann = ann_sweep.build_report(corpus_root=corpus)
        _write_json(target / "ann_sweep.json", ann)
        produced["ann_sweep.json"] = ann_sweep.markdown_summary(ann)

        _run_script(
            api_root,
            "evaluate_nctb_retrieval.py",
            str(corpus),
            "--out",
            str(target / "nctb_retrieval_eval.json"),
        )
        produced["nctb_retrieval_eval.json"] = {"script": "scripts/evaluate_nctb_retrieval.py"}
    else:
        produced["corpus_artifacts"] = (
            "SKIPPED: --no-corpus or no built corpus at data/nctb/normalized; "
            "run scripts/build_nctb_corpus.py first"
        )

    status_after = _git_status(repo_root)
    new_changes = sorted(set(status_after) - set(status_before))
    versions = versions_block(api_root)
    elapsed = round(time.perf_counter() - started, 1)

    summary = {
        "generated_by": "bangla_gpt_api.evaluation.rag_eval",
        "run_id": run_id,
        "out_dir": str(target),
        "elapsed_seconds": elapsed,
        "seed": seed,
        "versions": versions,
        "artifacts": sorted(produced),
        "tracked_tree": {
            "status_before": status_before,
            "status_after": status_after,
            "new_changes": new_changes,
            "clean": not new_changes,
            "note": (
                "new_changes lists tracked-file changes that appeared during the run; "
                "an empty list is the A8-10 property (one command, no tree mutation)"
            ),
        },
        "gate": {"passed": passed, "lines": lines},
        "highlights": {
            "targets_met": targets["met"],
            "targets_unmet": targets["unmet"],
            "redteam_leaks": len(leaks),
        },
    }
    _write_json(target / "summary.json", summary)
    markdown = render_summary_markdown(summary, produced)
    (target / "summary.md").write_text(markdown, encoding="utf-8")
    summary["summary_markdown"] = str(target / "summary.md")
    return summary


def _run_script(api_root: Path, script: str, *args: str) -> None:
    """Run one evaluation script from apps/api with the current interpreter."""
    completed = subprocess.run(  # noqa: S603 - fixed argv built here, never user input
        [sys.executable, str(api_root / "scripts" / script), *args],
        cwd=api_root,
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"{script} failed (exit {completed.returncode}): {completed.stderr.strip()[-600:]}"
        )


def render_summary_markdown(summary: dict[str, Any], produced: dict[str, Any]) -> str:
    """The one-page markdown the command writes beside the JSON artifacts.

    Every showcased number is copied out of an artifact in the same directory
    (never retyped), so the summary cannot drift from the JSON beside it.
    """
    versions = summary["versions"]
    tracked = summary["tracked_tree"]
    lines = [
        f"# RAG evaluation run {summary['run_id']}",
        "",
        f"- elapsed: {summary['elapsed_seconds']} s",
        f"- seed: {summary['seed']}",
        f"- python: {versions['python']} on {versions['platform']}",
        f"- prompt version: `{versions['prompt_version']}`",
        f"- golden dataset: {versions['golden'].get('dataset_hash')} "
        f"(test split {versions['golden'].get('test_split_hash')}, "
        f"{versions['golden'].get('items')} items)",
        f"- tracked tree clean during the run: **{tracked['clean']}**"
        + (f" (new changes: {tracked['new_changes']})" if tracked["new_changes"] else ""),
        "",
        "## Gate",
        "",
        f"- regression gate: {'PASS' if summary['gate']['passed'] else 'FAIL'}",
        f"- red-team leaks: {summary['highlights']['redteam_leaks']}",
        f"- targets met: {', '.join(summary['highlights']['targets_met']) or '(none)'}",
        f"- targets unmet: {', '.join(summary['highlights']['targets_unmet']) or '(none)'}",
        "",
        "## Artifacts",
        "",
    ]
    for name in summary["artifacts"]:
        payload = produced.get(name)
        lines.append(f"### {name}")
        lines.append("")
        if isinstance(payload, str):
            lines.append(payload)
        elif payload is not None:
            lines.append(f"```json\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n```")
        lines.append("")
    lines.append("## Packages")
    lines.append("")
    lines.append(", ".join(f"{name}={value}" for name, value in versions["packages"].items()))
    lines.append("")
    return "\n".join(lines)


__all__ = ["DEFAULT_RUN_ROOT", "render_summary_markdown", "run_rag_eval", "versions_block"]
