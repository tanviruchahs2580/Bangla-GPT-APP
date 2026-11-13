"""The v2 benchmark sweep runs hermetically and reports its contract.

The owner's requirement: candidate pool and top-K are swept, not assumed.
This pins the harness's shape (grid cells, Wilson CIs, the locked-contract
note) on a capped smoke run so the CI stays fast; the full 427-item sweep
is an operator/CI-artifact run of the same script.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_retrieval_v2.py"


def test_sweep_runs_hermetically_and_reports_the_grid(tmp_path: Path) -> None:
    out = tmp_path / "bench.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--max-items", "8", "--output", str(out)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=SCRIPT.parents[1],
    )
    assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-500:]
    payload = json.loads(out.read_text(encoding="utf-8"))
    cells = payload["cells"]
    # 4 candidate factors x 3 rrf_k x 2 neighbor states
    assert len(cells) == 24
    for cell in cells:
        assert {
            "candidate_factor",
            "rrf_k",
            "neighbor_expansion",
            "hit_at_3",
            "grounded_accuracy",
            "refusal_rate",
            "grounded_accuracy_ci",
        } <= set(cell)
    assert "LOCKED grounding contract" in result.stdout
    assert "shipped defaults" in result.stdout
