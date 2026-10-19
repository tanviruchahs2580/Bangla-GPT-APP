"""A8-07 / AUD-A2-13: pre-registered thresholds and the change-management hook.

The audit found no pre-registration anywhere: no primary metric, no split, no
decision rule written down *before* comparing variants, and no versioned
thresholds, so "the gate passed" could always be a post-hoc reading. This
module is the hook that makes the written pre-registration authoritative:

* :func:`load_thresholds` validates ``eval/thresholds_v1.json`` (version
  matches the changelog, the gate tolerance matches the code constant that CI
  actually enforces, every target carries a comparison);
* :func:`validate_revision` is the change-management hook: comparing the
  committed thresholds with a proposed revision, it fails when the version was
  not bumped, when a numeric threshold moved without a changelog entry naming
  the direction, or when a target was lowered without a written reason;
* :func:`required_evidence` lists the artifacts a model / prompt / index /
  embedding change must produce before it can be evaluated against the
  pre-registration, and :func:`missing_evidence` reports which are absent --
  the checklist an operator (or a CI job) runs before merging such a change.

Printing belongs to :mod:`bangla_gpt_api.evaluation.cli`
(``--check-thresholds``); this module raises or returns structured results so
it stays importable from tests and CI glue alike.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REQUIRED_KEYS = ("version", "recorded_at", "gate", "targets", "changelog")
_COMPARISONS = {">=", "<=", "=="}

#: Change kinds the change-management hook knows, and the evidence each one
#: must produce (repo-relative, from the repository root). The generation
#: report carries the red-team refusal correctness, so a model or prompt
#: change is covered by it; an index or embedding change moves ranks, so the
#: stratified retrieval report plus the real-corpus retrieval eval are the
#: artifacts that must be regenerated.
_REQUIRED_EVIDENCE: dict[str, tuple[str, ...]] = {
    "model": ("apps/api/eval/generation_report.json",),
    "prompt": ("apps/api/eval/generation_report.json",),
    "index": ("apps/api/eval/strata_report.json", "data/nctb/retrieval_eval.json"),
    "embedding": ("apps/api/eval/strata_report.json", "data/nctb/retrieval_eval.json"),
}


class ThresholdError(Exception):
    """A thresholds file or a proposed revision violates the pre-registration."""


def default_path(api_root: Path) -> Path:
    return api_root / "eval" / "thresholds_v1.json"


def load_thresholds(path: Path) -> dict[str, Any]:
    """Load and validate the versioned thresholds file.

    Validation is deliberately strict about the *bookkeeping* (a version with
    no changelog entry is a change nobody wrote down) and permissive about the
    numbers themselves -- moving a target is allowed when it is declared.
    """
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in _REQUIRED_KEYS if key not in payload]
    if missing:
        raise ThresholdError(f"{path.name} missing keys: {missing}")
    version = payload["version"]
    changelog = payload["changelog"]
    if not isinstance(version, int) or version < 1:
        raise ThresholdError(f"{path.name}: version must be a positive integer")
    if len(changelog) != version:
        raise ThresholdError(
            f"{path.name}: version {version} but {len(changelog)} changelog entries "
            "-- exactly one entry per version"
        )
    seen = [entry.get("version") for entry in changelog]
    if seen != list(range(1, version + 1)):
        raise ThresholdError(f"{path.name}: changelog versions must be 1..{version}, got {seen}")
    if not payload["gate"].get("tolerance_pp") or not payload.get("primary_metric"):
        raise ThresholdError(f"{path.name}: gate.tolerance_pp and primary_metric are required")
    targets = payload["targets"]
    if not targets:
        raise ThresholdError(f"{path.name}: at least one target is required")
    for name, spec in targets.items():
        if spec.get("comparison") not in _COMPARISONS:
            raise ThresholdError(
                f"{path.name}: target {name!r} needs a comparison in {sorted(_COMPARISONS)}"
            )
        if not isinstance(spec.get("target"), int | float):
            raise ThresholdError(f"{path.name}: target {name!r} needs a numeric target")
    return payload


def validate_against_code(thresholds: dict[str, Any]) -> None:
    """The gate tolerance and primary metric must match the code that runs.

    This is the anti-drift pin: thresholds_v1.json describes what CI enforces,
    so a silent change to ``metrics.GATE_PP`` or to the primary retrieval
    metric without a thresholds revision fails here.
    """
    from bangla_gpt_api.evaluation.metrics import GATE_PP
    from bangla_gpt_api.evaluation.retrieval_strata import PRIMARY_METRIC

    tolerance = float(thresholds["gate"]["tolerance_pp"])
    if abs(tolerance - GATE_PP) > 1e-9:
        raise ThresholdError(
            f"gate.tolerance_pp={tolerance} does not match metrics.GATE_PP={GATE_PP}: "
            "the pre-registration and the CI gate disagree"
        )
    if thresholds["primary_metric"] != PRIMARY_METRIC:
        raise ThresholdError(
            f"primary_metric={thresholds['primary_metric']!r} does not match the "
            f"retrieval metric layer's {PRIMARY_METRIC!r}"
        )


def validate_revision(old: dict[str, Any], new: dict[str, Any]) -> None:
    """Change-management hook: a revised thresholds file must declare its changes.

    Raises :class:`ThresholdError` when the version was not bumped, when a
    numeric threshold moved without a changelog entry that names it, or when a
    target was lowered without a stated reason (the entry must carry a
    non-empty ``moved_from`` note explaining why).
    """
    if new["version"] <= old["version"]:
        raise ThresholdError(
            f"thresholds revision must bump version (old {old['version']} -> new "
            f"{new['version']}): a revision without a version is an unrecorded change"
        )
    entry = new["changelog"][-1]
    if entry.get("version") != new["version"]:
        raise ThresholdError("the last changelog entry must describe the new version")

    moved = _moved_values(old, new)
    if moved and not entry.get("change"):
        raise ThresholdError(
            f"moved thresholds {sorted(moved)} need a changelog entry naming each change"
        )
    lowered = {name: (before, after) for name, (before, after) in moved.items() if after < before}
    if lowered and not str(entry.get("moved_from") or "").strip():
        raise ThresholdError(
            f"lowered targets {sorted(lowered)} require a written reason in the "
            "changelog entry's moved_from field"
        )


def _moved_values(old: dict[str, Any], new: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """Numeric target/tolerance moves, ``{name: (before, after)}``."""
    moved: dict[str, tuple[float, float]] = {}
    old_tol = float(old["gate"]["tolerance_pp"])
    new_tol = float(new["gate"]["tolerance_pp"])
    if old_tol != new_tol:
        moved["gate.tolerance_pp"] = (old_tol, new_tol)
    for name, spec in new["targets"].items():
        before = old["targets"].get(name)
        if before is None:
            continue
        if float(before["target"]) != float(spec["target"]):
            moved[name] = (float(before["target"]), float(spec["target"]))
    return moved


def required_evidence(change_kind: str) -> tuple[str, ...]:
    """Artifacts a change of this kind must produce (see ``_REQUIRED_EVIDENCE``)."""
    if change_kind not in _REQUIRED_EVIDENCE:
        raise ThresholdError(
            f"unknown change kind {change_kind!r}; known: {sorted(_REQUIRED_EVIDENCE)}"
        )
    return _REQUIRED_EVIDENCE[change_kind]


def missing_evidence(change_kind: str, repo_root: Path) -> list[str]:
    """Which required artifacts for this change kind do not exist on disk."""
    return [
        relative
        for relative in required_evidence(change_kind)
        if not (repo_root / relative).exists()
    ]


def stale_evidence(change_kind: str, repo_root: Path, changed_paths: list[Path]) -> list[str]:
    """Required artifacts older than the newest changed source file.

    Evidence recorded *before* the change is not evidence about the change.
    Compares mtimes, which is what the working tree offers without git; a CI
    integration with a commit range would use committer dates instead.
    """
    if not changed_paths:
        return []
    newest = max(path.stat().st_mtime for path in changed_paths if path.exists())
    stale = []
    for relative in required_evidence(change_kind):
        artifact = repo_root / relative
        if artifact.exists() and artifact.stat().st_mtime < newest:
            stale.append(relative)
    return stale
