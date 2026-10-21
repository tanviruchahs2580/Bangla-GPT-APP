"""The operational scripts must import and expose their documented entry points.

Wave 5 moved the judge harness out of ``evaluation/generation.py`` and updated
the package's importers but not ``scripts/evaluate_live.py``, whose
``judge_prompt_version`` import then failed at run time -- in the nightly
live-eval job, not in CI: no test imports a script. This is that test, cheap
and hermetic: every script module is imported (no network, no provider) and its
entry points are checked to exist, so a moved name fails here instead of in a
scheduled job nobody is watching.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = API_ROOT / "scripts"
SRC = API_ROOT / "src"

#: Scripts whose module-level code must be importable without side effects.
#: Registry: add a script here when it grows an entry point something else
#: (a workflow, a Makefile target, a document) calls by name.
IMPORTABLE = {
    "evaluate_live": ("_load_items", "main", "_api_key"),
    "ttft_profile": ("run_ttft_profile", "_StartPacer", "_percentiles"),
    "_live_common": ("_api_key", "_load_items", "_redteam_items"),
    "evaluate_replay": ("_rates", "compare_rates", "_load_items"),
    "evaluate_nctb_retrieval": ("main",),
    "extraction_audit": ("main",),
    "gen_golden_v2": ("main", "_clauses", "_content_terms"),
    "strata_report": ("main",),
}


def _load(name: str) -> ModuleType:
    """Import a script by path, with the package and sibling scripts importable."""
    for path in (str(SRC), str(SCRIPTS)):
        if path not in sys.path:
            sys.path.insert(0, path)
    spec = importlib.util.spec_from_file_location(f"bgpt_script_{name}", SCRIPTS / f"{name}.py")
    assert spec and spec.loader, name
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", sorted(IMPORTABLE))
def test_script_imports_and_exposes_its_entry_points(name: str) -> None:
    module = _load(name)
    for attribute in IMPORTABLE[name]:
        assert hasattr(module, attribute), f"{name}.{attribute} is gone"


def test_live_runner_reads_the_judge_from_its_module() -> None:
    """The regression that motivated this file: the runner imported the judge
    harness from `evaluation.generation` after it moved to `evaluation.judge`."""
    source = (SCRIPTS / "evaluate_live.py").read_text(encoding="utf-8")
    assert "judge_prompt_version" in source
    assert "from bangla_gpt_api.evaluation.judge import" in source, (
        "the judge harness lives in evaluation/judge.py; importing it from "
        "generation.py breaks the live run at run time"
    )
