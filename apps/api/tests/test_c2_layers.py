"""C-02: the dependency rule is enforced by tooling, not by convention.

AUD-CD-19 recorded the state this module pins: the import graph happened to be
acyclic on the day of the audit, but nothing prevented the next refactor from
introducing a cycle or an upward import (ADR-0001 itself says "enforced by
convention"). ``scripts/check_layers.py`` is the tool; these tests are its
proof and its anti-rot guard:

* the real tree passes (zero cycles, no upward imports);
* every rule *bites*: a synthetic upward import, a transport import from the
  service layer and a synthetic cycle are all reported;
* the exception table cannot rot: each entry carries a reason and must still
  match a real edge, so a fixed exception fails the gate instead of lingering.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest

APP = Path(__file__).resolve().parents[1]
SCRIPT = APP / "scripts" / "check_layers.py"


def _load_checker() -> Any:
    spec = importlib.util.spec_from_file_location("check_layers", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules[cls.__module__],
    # so the module must be registered before it is executed.
    sys.modules["check_layers"] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
PACKAGE = checker.PACKAGE


@pytest.fixture(scope="module")
def graph() -> dict[str, set[str]]:
    # ``checker`` is loaded by path (importlib), so mypy sees Any; the cast
    # states the shape once instead of disabling the check at every use.
    return cast("dict[str, set[str]]", checker.build_graph())


@pytest.fixture(scope="module")
def module_graph() -> dict[str, set[str]]:
    """Module-level edges only: the graph that decides import order."""
    return cast("dict[str, set[str]]", checker.build_module_graph())


# ---------------------------------------------------------------- real tree --


def test_repository_satisfies_every_rule(graph, module_graph) -> None:
    violations = checker.all_violations(graph, module_graph)
    assert violations == [], "\n".join(v.render() for v in violations)


def test_repository_has_zero_module_level_cycles(module_graph) -> None:
    """A module-level cycle is a load-order bug: never allowed, no exception."""
    assert checker.find_cycles(module_graph) == []


def test_repository_has_no_unregistered_function_local_cycles(graph, module_graph) -> None:
    """Coupling warts are allowed only when written down with a reason."""
    strict = {frozenset(members) for members in checker.find_cycles(module_graph)}
    lazy = [members for members in checker.find_cycles(graph) if frozenset(members) not in strict]
    unregistered = [m for m in lazy if frozenset(m) not in checker.ALLOWED_LAZY_CYCLES]
    assert unregistered == [], f"unregistered function-local cycles: {unregistered}"


def test_graph_is_actually_populated(graph) -> None:
    """A checker that silently walks nothing would pass every other test."""
    assert len(graph) > 100
    assert sum(len(targets) for targets in graph.values()) > 300


def test_every_module_is_classified(graph) -> None:
    unclassified = [name for name in graph if checker.layer_of(name) is None]
    assert unclassified == []


# ------------------------------------------------------------------- rules --


def test_upward_import_is_rejected() -> None:
    synthetic = {f"{PACKAGE}.services.fake": {f"{PACKAGE}.routers.fake"}}
    rendered = [v.render() for v in checker.all_violations(synthetic)]
    assert any("[layer]" in line for line in rendered)
    assert any("[transport-import]" in line for line in rendered)


def test_downward_import_is_allowed() -> None:
    synthetic = {
        f"{PACKAGE}.routers.fake": {f"{PACKAGE}.services.fake"},
        f"{PACKAGE}.services.fake": {f"{PACKAGE}.db.fake", f"{PACKAGE}.config"},
    }
    assert checker.all_violations(synthetic) == []


def test_transport_may_be_imported_by_the_composition_surface() -> None:
    synthetic = {
        f"{PACKAGE}.initialize.dependencies": {f"{PACKAGE}.routers.deps"},
        f"{PACKAGE}.main": {f"{PACKAGE}.routers"},
    }
    assert checker.all_violations(synthetic) == []


def test_cycle_is_detected_and_reported_with_members() -> None:
    synthetic = {
        f"{PACKAGE}.services.a": {f"{PACKAGE}.services.b"},
        f"{PACKAGE}.services.b": {f"{PACKAGE}.services.c"},
        f"{PACKAGE}.services.c": {f"{PACKAGE}.services.a"},
    }
    cycles = checker.find_cycles(synthetic)
    assert cycles == [[f"{PACKAGE}.services.a", f"{PACKAGE}.services.b", f"{PACKAGE}.services.c"]]
    rendered = " ".join(v.render() for v in checker.all_violations(synthetic))
    assert "[cycle]" in rendered


def test_module_level_and_lazy_cycles_are_reported_differently() -> None:
    """A function-local cycle is still a violation, but a named class of one."""
    full = {
        f"{PACKAGE}.services.a": {f"{PACKAGE}.services.b"},
        f"{PACKAGE}.services.b": {f"{PACKAGE}.services.a"},
    }
    strict: dict[str, set[str]] = {f"{PACKAGE}.services.a": set(), f"{PACKAGE}.services.b": set()}
    rendered = " ".join(v.render() for v in checker.all_violations(full, strict))
    assert "[lazy-cycle]" in rendered and "ALLOWED_LAZY_CYCLES" in rendered

    registered = {frozenset(full): "a reason long enough to be a real justification"}
    original = checker.ALLOWED_LAZY_CYCLES.copy()
    checker.ALLOWED_LAZY_CYCLES.clear()
    checker.ALLOWED_LAZY_CYCLES.update(registered)
    try:
        assert checker.all_violations(full, strict) == []
    finally:
        checker.ALLOWED_LAZY_CYCLES.clear()
        checker.ALLOWED_LAZY_CYCLES.update(original)


def test_module_level_cycle_cannot_be_allowlisted() -> None:
    """The hard class ignores the lazy allowlist entirely."""
    full = {
        f"{PACKAGE}.services.a": {f"{PACKAGE}.services.b"},
        f"{PACKAGE}.services.b": {f"{PACKAGE}.services.a"},
    }
    original = checker.ALLOWED_LAZY_CYCLES.copy()
    checker.ALLOWED_LAZY_CYCLES.clear()
    checker.ALLOWED_LAZY_CYCLES.update({frozenset(full): "an attempt to silence it"})
    try:
        rendered = " ".join(v.render() for v in checker.all_violations(full, full))
    finally:
        checker.ALLOWED_LAZY_CYCLES.clear()
        checker.ALLOWED_LAZY_CYCLES.update(original)
    assert "[cycle]" in rendered and "load-order bug" in rendered


def test_dag_is_not_reported_as_cycle() -> None:
    synthetic = {
        f"{PACKAGE}.services.a": {f"{PACKAGE}.services.b"},
        f"{PACKAGE}.services.b": {f"{PACKAGE}.services.c"},
    }
    assert checker.find_cycles(synthetic) == []


def test_unclassified_module_is_reported() -> None:
    synthetic: dict[str, set[str]] = {f"{PACKAGE}.not_a_real_layer.thing": set()}
    rendered = [v.render() for v in checker.check_layers(synthetic)]
    assert any("not in the LAYERS table" in line for line in rendered)


def test_function_local_imports_count() -> None:
    """The codebase's deliberate lazy edges live inside functions."""
    imports = checker.module_imports(
        f"{PACKAGE}.services.fake",
        APP / "src" / PACKAGE.replace(".", "/") / "jobs.py",
        known=checker.discover_modules(),
    )
    assert f"{PACKAGE}.services.parent_digest" in imports  # imported inside a function


# -------------------------------------------------------------- exceptions --


def test_every_exception_has_a_reason() -> None:
    assert checker.EXCEPTIONS, "an empty table is fine only while no reverse edge exists"
    for (importer, imported), reason in checker.EXCEPTIONS.items():
        assert len(reason.strip()) > 40, f"{importer} -> {imported} needs a real reason"


def test_every_allowed_lazy_cycle_has_a_reason_and_is_live(graph, module_graph) -> None:
    """The lazy-cycle table must not rot into a silence switch either."""
    assert checker.ALLOWED_LAZY_CYCLES, "a table with no entries belongs deleted"
    strict = {frozenset(members) for members in checker.find_cycles(module_graph)}
    observed = {frozenset(members) for members in checker.find_cycles(graph)} - strict
    for members, reason in checker.ALLOWED_LAZY_CYCLES.items():
        assert len(reason.strip()) > 80, f"{sorted(members)} needs a real justification"
        assert members in observed, f"{sorted(members)} is no longer a cycle; delete the entry"


def test_no_stale_exceptions(graph) -> None:
    """A fixed exception must be deleted, not left as a silence switch."""
    for importer, imported in checker.EXCEPTIONS:
        live = any(
            (source == importer or source.startswith(f"{importer}."))
            and any(target == imported or target.startswith(f"{imported}.") for target in targets)
            for source, targets in graph.items()
        )
        assert live, f"exception {importer} -> {imported} no longer matches a real edge"


# ---------------------------------------------------------------------- CLI --


def test_cli_exit_codes_and_json(capsys) -> None:
    assert checker.main([]) == 0
    assert "ok" in capsys.readouterr().out

    assert checker.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["violations"] == [] and payload["modules"] > 100

    assert checker.main(["--list"]) == 0
    assert "layers (low -> high)" in capsys.readouterr().out
