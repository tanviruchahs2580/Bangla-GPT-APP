"""A9-05: the load harness's statistics and saturation logic.

The harness itself is verified by the archived runs in
`apps/api/eval/load_report.json` (it is the only way to exercise a real
server); these tests pin the parts that decide what those numbers mean, so a
regression in the interpretation is caught without a five-minute run.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "loadgen.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("loadgen", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _level(concurrency: int, p95: float, *, errors: int = 0, rps: float = 20.0) -> dict:
    return {
        "concurrency": concurrency,
        "requests": 40,
        "wall_seconds": 2.0,
        "throughput_rps": rps,
        "status_counts": {"200": 40 - errors, "429": errors},
        "errors": errors,
        "error_rate": errors / 40,
        "ask": {"n": 32, "p50_ms": p95 / 2, "p95_ms": p95, "p99_ms": p95 * 1.2, "mean_ms": p95 / 2},
        "dashboard": {"n": 8, "p50_ms": p95 / 3, "p95_ms": p95, "p99_ms": p95 * 1.3},
    }


def test_percentile_is_nearest_rank_and_empty_safe() -> None:
    module = _load_script()
    assert module._percentile([], 0.95) == 0.0
    values = [float(value) for value in range(1, 101)]
    assert module._percentile(values, 0.5) == 51.0
    assert module._percentile(values, 0.95) == 96.0


def test_flat_run_reports_no_saturation() -> None:
    module = _load_script()
    levels = [_level(1, 100.0, rps=20), _level(4, 150.0, rps=45), _level(8, 200.0, rps=50)]
    notes = module.saturation_notes(levels)
    assert notes["saturated"] is False
    assert notes["peak_throughput_concurrency"] == 8
    assert "no saturation observed" in notes["note"]


def test_errors_beyond_the_cap_saturate() -> None:
    module = _load_script()
    levels = [_level(1, 100.0), _level(4, 150.0, errors=4), _level(8, 160.0)]
    notes = module.saturation_notes(levels)
    assert notes["saturated"] is True
    assert notes["first_saturated_concurrency"] == 4
    assert any("error rate" in observation for observation in notes["observations"])


def test_latency_knee_saturates_before_errors_do() -> None:
    module = _load_script()
    levels = [_level(1, 100.0), _level(4, 120.0), _level(8, 800.0)]
    notes = module.saturation_notes(levels)
    assert notes["saturated"] is True
    assert notes["first_saturated_concurrency"] == 8


def test_report_records_mode_and_unmeasured_limits() -> None:
    module = _load_script()
    report = module.build_report(
        [_level(1, 100.0)], base_url="http://127.0.0.1:9", mode=module.MODE_CAPACITY
    )
    assert report["mode"] == module.MODE_CAPACITY
    assert "raised" in report["run_conditions"]["rate_limits"]
    assert any("time-to-first-token" in item for item in report["unmeasured"])
    assert report["budgets"]["full_answer_p95_ms"] == 12000
    limits = module.build_report(
        [_level(1, 100.0)], base_url="http://127.0.0.1:9", mode=module.MODE_PRODUCT_LIMITS
    )
    assert "30 tutor requests/user/min" in limits["run_conditions"]["rate_limits"]


def test_question_pool_is_distinct_so_the_cache_cannot_absorb_the_load() -> None:
    module = _load_script()
    assert len(set(module.QUESTIONS)) == len(module.QUESTIONS) >= 8
