#!/usr/bin/env python
"""Quality ratchets: freeze today's violations, fail on new ones (C-03/D-03/D-04/D-05).

The audit found five quality dimensions measured *for the audit* but not
enforced anywhere: cyclomatic complexity (radon: 67 blocks at rank C or worse,
11 at D or worse), oversized modules (20 files over 500 lines, worst 1464),
dead code (vulture: clean at --min-confidence 80 today), dependency hygiene
(deptry: 15 accepted findings, all triaged in pyproject comments) and copy-paste
duplication (jscpd: 2.49% of lines across 263 files).

Gates that demand "zero complexity" or "zero duplication" today would either
never go green or invite the usual cheat of loosening a threshold. A ratchet is
the honest version: every existing violation is written into a committed
baseline, the gate fails when a *new* one appears or an existing one grows, and
improvements need no baseline edit (ratchet tightens itself).

Usage
-----
    python scripts/check_quality_ratchet.py --check [GATE ...]
    python scripts/check_quality_ratchet.py --update [GATE ...]
    python scripts/check_quality_ratchet.py --report          # current state only

GATE is one of complexity, file-size, dead-code, deps, duplication; with no
name, all of them run. Exit codes: 0 clean, 1 new violations, 2 tooling missing.

Updating a baseline is a deliberate act: fix the violation, or justify it in
the commit message (and, for a dependency, in pyproject.toml) and run
``--update`` in the same commit.

External tools: radon, vulture, deptry (Python; to be added to the `dev` extra
in pyproject.toml) and `npx jscpd` (Node; pinned in the CI step that calls
this script). Each gate fails closed with exit 2 when its tool is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parents[1]  # apps/api
REPO = APP.parent.parent
BASELINE_DIR = APP / "quality-baselines"

CC_MIN = 11  # radon rank C and worse (A 1-5, B 6-10, C 11-20, D 21-30, E 31-40, F 41+)
MAX_LINES = 500
VULTURE_MIN_CONFIDENCE = 80
JSCPD_MIN_LINES = 6
JSCPD_MIN_TOKENS = 70
JSCPD_ROOTS = ["apps/api/src", "apps/web/src", "scripts"]

SKIP_DIRS = {
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "alembic/versions",
}
SIZE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".mjs", ".jsx", ".cjs"}
SIZE_ROOTS = ["apps/api/src", "apps/api/tests", "apps/api/scripts", "apps/web/src", "scripts"]


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _walk(roots: list[str], extensions: set[str]) -> list[Path]:
    files = []
    for root in roots:
        base = REPO / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in extensions:
                continue
            rel_parts = path.relative_to(REPO).parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            if "alembic" in rel_parts and "versions" in rel_parts:
                continue
            files.append(path)
    return sorted(set(files))


def _baseline_path(gate: str) -> Path:
    return BASELINE_DIR / f"{gate.replace('-', '_')}-baseline.json"


def _load_baseline(gate: str) -> dict[str, Any] | None:
    path = _baseline_path(gate)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_baseline(gate: str, payload: dict[str, Any]) -> None:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    payload["generated"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _baseline_path(gate).write_text(
        json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[{gate}] baseline written to {_rel(_baseline_path(gate))}")


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _python_tool_available(module: str) -> bool:
    return _run([sys.executable, "-c", f"import {module}"], APP).returncode == 0


# --------------------------------------------------------------------------- #
# complexity (radon)
# --------------------------------------------------------------------------- #
def complexity_violations() -> dict[str, int]:
    from radon.complexity import cc_visit

    found: dict[str, int] = {}
    for path in _walk([_rel(APP / "src")], {".py"}):
        source = path.read_text(encoding="utf-8")
        for block in cc_visit(source):
            if block.complexity >= CC_MIN:
                found[f"{_rel(path)}::{block.fullname}"] = block.complexity
    return found


def check_complexity(update: bool) -> list[str]:
    if not _python_tool_available("radon"):
        return ["TOOLING: radon is not installed (pip install radon)"]
    current = complexity_violations()
    if update:
        _write_baseline("complexity", {"cc_min": CC_MIN, "tool": "radon", "violations": current})
        return []
    baseline = _load_baseline("complexity")
    if baseline is None:
        return ["TOOLING: no complexity baseline committed"]
    known: dict[str, int] = baseline["violations"]
    problems = []
    for name, cc in sorted(current.items()):
        if name not in known:
            problems.append(f"NEW complexity violation {name} = {cc} (limit {CC_MIN})")
        elif cc > known[name]:
            problems.append(f"{name} grew from {known[name]} to {cc}")
    return problems


# --------------------------------------------------------------------------- #
# file size
# --------------------------------------------------------------------------- #
def file_sizes() -> dict[str, int]:
    sizes = {}
    for path in _walk(SIZE_ROOTS, SIZE_EXTENSIONS):
        lines = sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
        if lines > MAX_LINES:
            sizes[_rel(path)] = lines
    return sizes


def check_file_size(update: bool) -> list[str]:
    current = file_sizes()
    if update:
        _write_baseline("file_size", {"max_lines": MAX_LINES, "files": current})
        return []
    baseline = _load_baseline("file-size")
    if baseline is None:
        return ["TOOLING: no file-size baseline committed"]
    known: dict[str, int] = baseline["files"]
    problems = []
    for name, lines in sorted(current.items()):
        if name not in known:
            problems.append(f"NEW oversized file {name} = {lines} lines (limit {MAX_LINES})")
        elif lines > known[name]:
            problems.append(f"{name} grew from {known[name]} to {lines} lines")
    return problems


# --------------------------------------------------------------------------- #
# dead code (vulture)
# --------------------------------------------------------------------------- #
def check_dead_code(update: bool) -> list[str]:
    if not _python_tool_available("vulture"):
        return ["TOOLING: vulture is not installed (pip install vulture)"]
    whitelist = BASELINE_DIR / "vulture_whitelist.py"
    scan = [str((APP / "src").relative_to(APP))]
    if update:
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        result = _run(
            [
                sys.executable,
                "-m",
                "vulture",
                *scan,
                f"--min-confidence={VULTURE_MIN_CONFIDENCE}",
                "--make-whitelist",
            ],
            APP,
        )
        whitelist.write_text(result.stdout, encoding="utf-8")
        print(f"[dead-code] whitelist written to {_rel(whitelist)}")
        return []
    if not whitelist.exists():
        return ["TOOLING: no vulture whitelist committed"]
    result = _run(
        [
            sys.executable,
            "-m",
            "vulture",
            *scan,
            str(whitelist.relative_to(APP)),
            f"--min-confidence={VULTURE_MIN_CONFIDENCE}",
        ],
        APP,
    )
    findings = [line for line in result.stdout.splitlines() if line.strip()]
    return [f"NEW dead code: {line}" for line in findings]


# --------------------------------------------------------------------------- #
# dependency hygiene (deptry)
# --------------------------------------------------------------------------- #
def check_deps(update: bool) -> list[str]:
    if not _python_tool_available("deptry"):
        return ["TOOLING: deptry is not installed (pip install deptry)"]
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "deptry.json"
        _run([sys.executable, "-m", "deptry", ".", "-o", str(report)], APP)
        if not report.exists():
            return ["TOOLING: deptry produced no JSON report"]
        findings = json.loads(report.read_text(encoding="utf-8"))
    current = {
        f"{f['error']['code']}:{f['module']}:{f['location']['file']}": f["error"]["message"]
        for f in findings
    }
    if update:
        _write_baseline("deps", {"tool": "deptry", "accepted": current})
        return []
    baseline = _load_baseline("deps")
    if baseline is None:
        return ["TOOLING: no deps baseline committed"]
    known = baseline["accepted"]
    return [
        f"NEW dependency finding {key}: {message}"
        for key, message in sorted(current.items())
        if key not in known
    ]


# --------------------------------------------------------------------------- #
# duplication (jscpd)
# --------------------------------------------------------------------------- #
def _npx_command(args: list[str]) -> list[str]:
    exe = shutil.which("npx.cmd") or shutil.which("npx")
    if exe is None:
        return []
    return [exe, *args]


def _jscpd_identities(report_file: Path) -> dict[str, int]:
    report = json.loads(report_file.read_text(encoding="utf-8"))
    identities = {}
    for clone in report.get("duplicates", []):
        digest = hashlib.sha256(clone["fragment"].encode("utf-8")).hexdigest()[:16]
        files = sorted([clone["firstFile"]["name"], clone["secondFile"]["name"]])
        files = [f.replace("\\", "/") for f in files]
        identities[f"{digest}:{files[0]}~{files[1]}"] = clone["lines"]
    return identities


def check_duplication(update: bool, report_only: bool = False) -> list[str]:
    cmd = _npx_command(
        [
            "jscpd",
            *JSCPD_ROOTS,
            f"--min-lines={JSCPD_MIN_LINES}",
            f"--min-tokens={JSCPD_MIN_TOKENS}",
            "--reporters",
            "json",
            "--silent",
        ]
    )
    if not cmd:
        return ["TOOLING: npx/jscpd not available"]
    with tempfile.TemporaryDirectory() as tmp:
        cmd += ["--output", tmp]
        result = _run(cmd, REPO)
        report_file = Path(tmp) / "jscpd-report.json"
        if not report_file.exists():
            return [f"TOOLING: jscpd produced no report (exit {result.returncode})"]
        current = _jscpd_identities(report_file)
        stats = json.loads(report_file.read_text(encoding="utf-8"))["statistics"]["total"]
    print(
        f"[duplication] {stats['clones']} clones, {stats['duplicatedLines']} duplicated lines "
        f"({stats['percentage']:.2f}%), {stats['sources']} files scanned"
    )
    if report_only:
        return []
    if update:
        _write_baseline(
            "duplication",
            {
                "tool": "jscpd",
                "min_lines": JSCPD_MIN_LINES,
                "min_tokens": JSCPD_MIN_TOKENS,
                "roots": JSCPD_ROOTS,
                "clones": current,
            },
        )
        return []
    baseline = _load_baseline("duplication")
    if baseline is None:
        return ["TOOLING: no duplication baseline committed"]
    known = baseline["clones"]
    return [
        f"NEW duplicate block {lines} lines: {key.split(':', 1)[1]}"
        for key, lines in sorted(current.items())
        if key not in known
    ]


GATES = {
    "complexity": check_complexity,
    "file-size": check_file_size,
    "dead-code": check_dead_code,
    "deps": check_deps,
    "duplication": check_duplication,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail on new violations")
    mode.add_argument("--update", action="store_true", help="rewrite the baselines")
    mode.add_argument("--report", action="store_true", help="print current state only")
    parser.add_argument("gates", nargs="*", choices=[*GATES, "all"])
    args = parser.parse_args(argv)

    selected = args.gates or ["all"]
    gates = list(GATES) if "all" in selected else selected

    failures: list[str] = []
    for gate in gates:
        if args.report and gate == "duplication":
            check_duplication(update=False, report_only=True)
            continue
        if args.report:
            continue
        problems = GATES[gate](update=args.update)
        tooling = [p for p in problems if p.startswith("TOOLING")]
        if tooling:
            print(f"[{gate}] {tooling[0]}", file=sys.stderr)
            failures.extend(tooling)
            continue
        for problem in problems:
            print(f"[{gate}] {problem}")
        if problems:
            failures.extend(problems)
        else:
            print(f"[{gate}] ok")

    if any(f.startswith("TOOLING") for f in failures):
        return 2
    if failures:
        print(
            f"\n{len(failures)} new quality violation(s). Fix them, or record a "
            "justified update with --update in the same commit."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
