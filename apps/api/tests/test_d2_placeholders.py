"""Placeholder/stub static sweep rules (AUD-CD-10 / D-16).

`scripts/check_placeholders.py` is the repeatable form of the audit's ad-hoc
S-01 greps. These tests pin its rule set (so a future edit cannot silently
loosen it), its interface exceptions (Protocol/ABC members are not stubs), the
allowlist discipline (every entry carries a reason), and prove the gate fails
on a planted placeholder and passes on the real tree.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "check_placeholders.py"

_spec = importlib.util.spec_from_file_location("check_placeholders", SCRIPT)
check_placeholders = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
# dataclasses resolve annotations through sys.modules; register before exec.
sys.modules["check_placeholders"] = check_placeholders
_spec.loader.exec_module(check_placeholders)


SRC = "apps/api/src/bangla_gpt_api/example_module.py"


def _rules(findings: list) -> list[str]:
    return [finding.rule for finding in findings]


def test_marker_finds_todo_and_fixme() -> None:
    findings = check_placeholders.scan_text(SRC, "# TODO: wire this up\nx = 1  # FIXME\n")
    assert _rules(findings) == ["marker", "marker"]
    assert findings[0].lineno == 1


def test_marker_does_not_flag_substrings() -> None:
    assert check_placeholders.scan_text(SRC, "todos = ['x']  # todoist import\n") == []


def test_placeholder_secret_and_lorem_are_flagged() -> None:
    text = 'SECRET = "changeme"\ncopy = "lorem ipsum dolor"\n'
    assert sorted(_rules(check_placeholders.scan_text(SRC, text))) == [
        "lorem",
        "placeholder-secret",
    ]


def test_coming_soon_promise_is_flagged() -> None:
    findings = check_placeholders.scan_text(SRC, 'toast("Export coming soon")\n')
    assert _rules(findings) == ["coming-soon"]


def test_fake_host_flagged_in_production_but_not_in_tests() -> None:
    production = check_placeholders.scan_text(SRC, 'BASE = "https://api.example.com"\n')
    assert _rules(production) == ["fake-host"]
    in_tests = check_placeholders.scan_text(
        "apps/api/tests/test_thing.py", 'EMAIL = "a@example.com"\n'
    )
    assert in_tests == []
    in_web_tests = check_placeholders.scan_text(
        "apps/web/src/test/thing.test.ts", 'const h = "https://a.example.com";\n'
    )
    assert in_web_tests == []


def test_not_implemented_raise_flagged_only_on_production_paths() -> None:
    assert _rules(
        check_placeholders.scan_text(SRC, "def f():\n    raise NotImplementedError\n")
    ) == ["not-implemented-raise"]
    assert (
        check_placeholders.scan_text(
            "apps/api/tests/test_double.py", "def f():\n    raise NotImplementedError\n"
        )
        == []
    )


def test_py_stub_flags_pass_only_and_docstring_only_functions() -> None:
    text = (
        "def placeholder():\n"
        "    pass\n"
        "\n"
        "def documented():\n"
        '    """Only a docstring."""\n'
        "\n"
        "def real():\n"
        "    return 1\n"
    )
    findings = check_placeholders.scan_python_stubs(SRC, text)
    assert [finding.snippet for finding in findings] == ["def placeholder", "def documented"]


def test_py_stub_skips_protocol_members_and_abstract_methods() -> None:
    text = (
        "from typing import Protocol\n"
        "from abc import ABC, abstractmethod\n"
        "\n"
        "class Store(Protocol):\n"
        "    def get(self) -> str:\n"
        "        ...\n"
        "\n"
        "class Base(ABC):\n"
        "    @abstractmethod\n"
        "    def build(self) -> None:\n"
        '        """Subclasses implement."""\n'
    )
    assert check_placeholders.scan_python_stubs(SRC, text) == []


def test_py_stub_reports_unparsable_production_file() -> None:
    findings = check_placeholders.scan_python_stubs(SRC, "def broken(:\n")
    assert _rules(findings) == ["py-stub"]
    assert "could not parse" in findings[0].line


def test_every_allow_entry_has_a_reason_for_a_real_rule() -> None:
    rule_names = {rule.name for rule in check_placeholders.RULES} | {"*"}
    for entry in check_placeholders.ALLOW:
        assert entry.rule in rule_names, entry
        assert entry.path_glob, entry
        assert len(entry.reason) >= 40, entry
        assert entry.reason[0].islower() or entry.reason[0].isupper(), entry


def test_wildcard_allowances_are_only_the_sweep_and_its_test() -> None:
    wildcards = [entry for entry in check_placeholders.ALLOW if entry.rule == "*"]
    assert [entry.path_glob for entry in wildcards] == [
        "scripts/check_placeholders.py",
        "apps/api/tests/test_d2_placeholders.py",
    ]
    assert all(entry.snippet is None for entry in wildcards)


def test_script_is_clean_on_the_repository() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no placeholder findings" in result.stdout
    assert "stale allowlist entry" not in result.stdout


def test_planted_placeholder_fails_the_gate(tmp_path: Path) -> None:
    planted = tmp_path / "apps" / "api" / "src"
    planted.mkdir(parents=True)
    (planted / "leaky.py").write_text('SECRET = "changeme"\n# TODO: remove\n', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "changeme" in result.stdout
    assert "placeholder sweep FAILED" in result.stdout


def test_empty_tree_fails_closed(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "could not run" in result.stderr
