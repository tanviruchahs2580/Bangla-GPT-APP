#!/usr/bin/env python
"""Per-module coverage floors for the critical paths (F-058 / TEST-02).

The global ``fail_under = 80`` (pyproject) says nothing about *where* the
coverage sits: a well-covered schema module can hide a thin authorization or
privacy path. This gate reads a coverage JSON report and enforces a floor per
module, so the critical surface can only get better.

The numbers are the full-suite branch coverage measured on 2026-10-30 (1667
tests, Python 3.12, SQLite); each floor is the measurement rounded down to a
whole percent, so the gate blocks a regression with headroom for a single
uncovered line and never fails on day one. The 90 target the audit set is met
by every module without a "gap" note; the rest record the gap explicitly and
the floor may only rise.

Usage:
    python -m coverage json -o coverage.json     # or pytest --cov-report=json
    python scripts/check_coverage_floors.py coverage.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: module (relative to src/bangla_gpt_api) -> (floor percent, note)
FLOORS: dict[str, tuple[float, str]] = {
    # --- authentication and sessions
    "auth/security.py": (96.0, ""),
    "auth/mfa.py": (90.0, ""),
    "auth/impersonation.py": (85.0, "gap to 90: the impersonation refusal paths"),
    "auth/single_use.py": (86.0, "gap to 90: the single-use token expiry paths"),
    # --- authorization and tenancy
    "routers/deps.py": (93.0, ""),
    "routers/auth.py": (89.0, "gap to 90: reset/MFA edge paths"),
    "routers/school.py": (96.0, ""),
    "routers/admin.py": (88.0, "gap to 90: admin maintenance paths"),
    "routers/users.py": (87.0, "gap to 90: profile/session revoke paths"),
    "routers/parent.py": (81.0, "gap to 90: parent digest/report paths"),
    # --- privacy and retention
    "services/pii.py": (100.0, ""),
    "services/gdpr.py": (98.0, ""),
    "services/retention.py": (98.0, ""),
    "security.py": (84.0, "gap to 90: PII crypto helpers"),
    # --- moderation and child safety
    "services/safety.py": (98.0, ""),
    # --- grounding / retrieval
    "services/answer_structure.py": (100.0, ""),
    "retrieval/hybrid.py": (100.0, ""),
    "retrieval/hybrid_index.py": (96.0, ""),
    "retrieval/bm25.py": (100.0, ""),
    "retrieval/embedding.py": (98.0, ""),
    # --- jobs and resilience
    "jobs.py": (89.0, "gap to 90: scheduler failure branches"),
    "services/circuit_breaker.py": (92.0, ""),
    "services/tutor.py": (91.0, ""),
    "ratelimit.py": (89.0, "gap to 90: Redis backend error branches"),
    "middleware.py": (94.0, ""),
}


def module_rates(report: dict) -> dict[str, float]:
    """Map ``bangla_gpt_api/<path>`` to its combined line+branch percentage."""
    rates: dict[str, float] = {}
    for path, info in report.get("files", {}).items():
        normalised = path.replace("\\", "/")
        marker = "bangla_gpt_api/"
        index = normalised.rfind(marker)
        if index == -1:
            continue
        rates[normalised[index + len(marker) :]] = float(info["summary"]["percent_covered"])
    return rates


def violations(rates: dict[str, float]) -> list[str]:
    out: list[str] = []
    for module, (floor, note) in sorted(FLOORS.items()):
        measured = rates.get(module)
        if measured is None:
            out.append(f"{module}: not present in the coverage report (floor {floor:.0f}%)")
        elif measured < floor:
            suffix = f" ({note})" if note else ""
            out.append(f"{module}: {measured:.2f}% < floor {floor:.0f}%{suffix}")
    return out


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    if not path.exists():
        print(f"coverage report not found: {path}", file=sys.stderr)
        return 2
    report = json.loads(path.read_text(encoding="utf-8"))
    rates = module_rates(report)
    failed = violations(rates)
    for line in failed:
        print(f"FLOOR VIOLATION: {line}", file=sys.stderr)
    below_target = [
        f"{module} {rates[module]:.2f}%"
        for module, (floor, note) in FLOORS.items()
        if note and rates.get(module, 0.0) < 90.0
    ]
    if below_target:
        print("below the 90% target (recorded gaps): " + ", ".join(sorted(below_target)))
    print(
        f"coverage floors: {len(FLOORS) - len(failed)}/{len(FLOORS)} modules at or above "
        f"their floor (global {report.get('totals', {}).get('percent_covered_display', '?')}%)"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
