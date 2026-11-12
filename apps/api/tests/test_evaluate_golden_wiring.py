"""The 24-question golden gate must gate the tutor production actually serves.

Wiring parity (evaluation.cli._build_tutor documents the rule): without
``term_stats`` the gate graded uniform per-term weights with no
roman/glossary resolution — a configuration no deployment runs. The script
now mirrors production wiring; the AST pin keeps it that way even though
the script itself lives outside the test import surface.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_golden.py"


def _tutor_call() -> ast.Call:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "TutorService":
            return node
    raise AssertionError("scripts/evaluate_golden.py no longer builds a TutorService")


def test_gate_builds_tutor_with_production_term_stats() -> None:
    keywords = {kw.arg for kw in _tutor_call().keywords}
    assert {"index", "provider", "term_stats"} <= keywords, sorted(keywords)


def test_gate_passes_end_to_end_with_the_parity_wiring() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=SCRIPT.parents[1],
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-800:]
    assert "grounded accuracy" in result.stdout
