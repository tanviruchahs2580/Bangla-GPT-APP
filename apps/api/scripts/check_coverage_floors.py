"""Per-module coverage floors on the six critical paths (E-03, R4-wsC).

The CI coverage gate enforces one overall ``fail_under`` (pyproject).
This script adds the item's second half: BRANCH-coverage floors on the six
critical paths the audit catalog names -- auth, authorization, tenancy,
scoring/grading, retention/purge, RAG abstention/citation -- parsed from the
JSON coverage report pytest produces with ``--cov-report=json``.

Floor values are set at MEASURED minus 2 percentage points (never above the
measured value; the -2pp margin absorbs noise between runs without letting a
real regression through). The basis of every floor is recorded next to it and
must be refreshed whenever the gate is re-calibrated:

    pytest <module tests> -q --cov=bangla_gpt_api --cov-branch --cov-report=json

Module mapping (this codebase's layout):
  - auth + authorization: ``bangla_gpt_api/auth/`` -- role claims, token
    single-use, require_* enforcement all live in the auth package here, so
    the catalog's two floors are merged into one module floor.
  - tenancy: ``bangla_gpt_api/db/tenancy.py`` (the ORM read-path tenant filter).
  - scoring/grading: ``bangla_gpt_api/services/quiz.py`` (+ quiz_explain).
  - retention/purge: ``bangla_gpt_api/services/retention.py``.
  - grounding/abstention: ``bangla_gpt_api/services/tutor`` (the package the
t    1814-line module was split into, C-03; the gate lives in ``retrieval.py``) (the
    regenerator + abstention gate; the only in-src implementation).

Usage:
    python scripts/check_coverage_floors.py coverage.json [--report-only]

Exit codes: 0 = all floors met, 1 = floor violation(s), 2 = malformed input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Floor calibration (R4-wsC, 2026-10-20): every floor = (branch % measured in
# the module's own named test suites on this tree) minus 2pp, rounded DOWN to
# the integer. The commands and raw coverage JSONs live in
# .audit/evidence/R4-wsc-e03/; re-measure and restate the basis whenever a
# floor is raised. These are CONSERVATIVE lower bounds only -- a fuller
# selection (the whole suite) measures higher, so the CI full-suite run sits
# above them by construction; the catalog's branch>=95 aspiration is NOT met
# on every critical module today and these floors make that state visible and
# regression-proof instead of papering over it. Never raise a floor above its
# recorded measurement.
FLOORS: dict[str, tuple[str, float, str]] = {
    # module prefix: (label, floor %, measured basis)
    "bangla_gpt_api/auth": (
        "auth+authorization",
        77.0,
        "measured 79.2 branch % (19/24) over tests/test_single_use_tokens.py + test_round2_auth_hardening.py + test_reset_token_invalidation.py, 2026-10-20 R4-wsC",
    ),
    "bangla_gpt_api/db/tenancy.py": (
        "tenancy",
        85.0,
        "measured 87.5 branch % (14/16) over test_r3_ws4_tenancy.py + test_school_tenancy_isolation.py + test_cross_school_content.py, 2026-10-20 R4-wsC",
    ),
    "bangla_gpt_api/services/quiz.py": (
        "scoring/grading",
        83.0,
        "measured 85.0 branch % (51/60) over test_quiz_explain.py + test_quiz_progress.py + test_shorttest.py, 2026-10-20 R4-wsC",
    ),
    "bangla_gpt_api/services/retention.py": (
        "retention/purge",
        60.0,
        "measured 62.5 branch % (5/8) over tests/test_b2_retention_purge.py, 2026-10-20 R4-wsC",
    ),
    "bangla_gpt_api/services/tutor": (
        "grounding/abstention",
        62.0,
        "measured 68.6 branch % (118/172) over the tutor seam tests (test_tutor_service_seams.py + "
        "test_tutor_api.py + test_rag2_streaming_contract.py + test_r5_citation_selection.py + "
        "test_r5_gate_arithmetic.py + test_bangla_matrix.py; CI's full run covers more), 2026-10-21: "
        "same floor, same critical path, now aggregated over the package the module was split into",
    ),
}


def branch_percent_for_paths(files: dict, prefix: str) -> tuple[float | None, int, int]:
    """Aggregate branch coverage over every file under a module prefix."""
    covered = 0
    total = 0
    for path, info in files.items():
        # coverage.py JSON keys are cwd/package-relative and OS-styled: CI
        # (cwd=apps/api, source=bangla_gpt_api) keys files as
        # "src/bangla_gpt_api/auth/security.py" while an in-run report keyed
        # from the package source root shows "\auth\security.py". Match on the
        # package-relative tail, normalising both sides.
        tail = prefix.replace("\\", "/").partition("bangla_gpt_api/")[2] or prefix.replace(
            "\\", "/"
        )
        norm = path.replace("\\", "/").lstrip("/")
        if norm.startswith("src/bangla_gpt_api/"):
            norm = norm[len("src/bangla_gpt_api/") :]
        if not (norm == tail or norm.startswith(tail + "/") or norm.endswith("/" + tail)):
            continue
        summary = info.get("summary", {})
        covered += summary.get("covered_branches", 0)
        total += summary.get("num_branches", 0)
    if total == 0:
        return None, covered, total
    return 100.0 * covered / total, covered, total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("coverage_json", type=Path, help="coverage.py JSON report")
    parser.add_argument(
        "--report-only", action="store_true", help="print the table; exit 0 regardless"
    )
    args = parser.parse_args(argv)

    try:
        data = json.loads(args.coverage_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"coverage-floors: cannot read {args.coverage_json}: {exc}", file=sys.stderr)
        return 2

    files = data.get("files", {})
    if not files:
        print("coverage-floors: report contains no file data", file=sys.stderr)
        return 2

    violations: list[str] = []
    print(f"{'critical path':<24}{'branch %':>10}{'floor':>8}{'branches':>12}  basis")
    for prefix, (label, floor, basis) in FLOORS.items():
        pct, covered, total = branch_percent_for_paths(files, prefix)
        if pct is None:
            print(
                f"{label:<24}{'n/a':>10}{floor:>8}{f'{covered}/{total}':>12}  NO BRANCH DATA under {prefix}"
            )
            violations.append(
                f"{label}: no branch data for {prefix} (is the module imported in this run?)"
            )
            continue
        marked = "" if pct >= floor else "  <-- BELOW FLOOR"
        print(f"{label:<24}{pct:>9.1f}%{floor:>7.0f}%{f'{covered}/{total}':>12}  {basis}{marked}")
        if pct < floor:
            violations.append(f"{label}: branch {pct:.1f}% < floor {floor:.0f}% ({basis})")

    if args.report_only:
        return 0
    if violations:
        print("\ncoverage-floors: FAIL")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("\ncoverage-floors: all critical-path floors met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
