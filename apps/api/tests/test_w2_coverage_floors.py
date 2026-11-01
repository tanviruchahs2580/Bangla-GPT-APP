"""F-058: the per-module coverage floor gate behaves like a gate.

The script is what a CI step will run; these tests pin its parsing (file paths
from the coverage JSON, Windows or POSIX), its refusal below a floor and its
acceptance above one. The floors themselves are measured values recorded in
``scripts/check_coverage_floors.py``.
"""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_coverage_floors.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_coverage_floors", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _report(entries: dict[str, float]) -> dict:
    return {
        "files": {path: {"summary": {"percent_covered": value}} for path, value in entries.items()},
        "totals": {"percent_covered_display": "99.00"},
    }


def test_module_rates_normalise_both_path_separators() -> None:
    module = _load()
    rates = module.module_rates(
        _report(
            {
                "src\\bangla_gpt_api\\services\\safety.py": 98.0,
                "src/bangla_gpt_api/services/pii.py": 100.0,
                "scripts/other.py": 50.0,
            }
        )
    )
    assert rates == {"services/safety.py": 98.0, "services/pii.py": 100.0}


def test_a_module_below_its_floor_is_a_violation() -> None:
    module = _load()
    floor, _note = module.FLOORS["services/safety.py"]
    failed = module.violations({"services/safety.py": floor - 1.0})
    assert any(line.startswith("services/safety.py:") for line in failed), failed


def test_a_module_at_its_floor_passes() -> None:
    module = _load()
    rates = {name: floor for name, (floor, _note) in module.FLOORS.items()}
    assert module.violations(rates) == []


def test_a_missing_module_is_a_violation_not_a_pass() -> None:
    module = _load()
    failed = module.violations({})
    assert len(failed) == len(module.FLOORS), "every floor must be reported as missing"
