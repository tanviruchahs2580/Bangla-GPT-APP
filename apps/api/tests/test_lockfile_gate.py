"""The lockfile gate must be able to fail.

The step it replaces could not. It ran `pip-compile --output-file
constraints.txt` inside the checkout -- overwriting the committed lock -- and
then read that freshly generated file back to assert that every dependency
named in `pyproject.toml` appears in it, which is true of any file compiled from
`pyproject.toml`. `CONTRIBUTING.md` promised a stale lock could not slip
through, and none of it was enforced.

The miss that proved it: Dependabot pinned `redis==8.1.0` in the lock while
`arq` requires `redis[hiredis]<6`. The guardrails job passed in 32 s and five
other jobs then died with `ResolutionImpossible`, so the whole
dependency-update queue stopped landing.

These tests exercise the replacement as a real subprocess against synthetic
locks, because the property that matters is its exit status.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "apps/api/scripts/check_lockfile.py"

PYPROJECT = """
[project]
name = "demo"
version = "0.0.0"
dependencies = [
    "redis>=5.0,<6",
    "arq>=0.26",
]
[project.optional-dependencies]
dev = ["pytest>=8"]
"""


def _run(pyproject: str, constraints: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    pyproject_path = tmp_path / "pyproject.toml"
    constraints_path = tmp_path / "constraints.txt"
    pyproject_path.write_text(pyproject, encoding="utf-8")
    constraints_path.write_text(constraints, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pyproject",
            str(pyproject_path),
            "--constraints",
            str(constraints_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_accepts_a_lock_that_satisfies_the_manifest(tmp_path: Path) -> None:
    result = _run(
        PYPROJECT,
        "redis==5.3.1 \\\n    --hash=sha256:aa\narq==0.28.0 \\\n    --hash=sha256:bb\n"
        "pytest==9.0.0 \\\n    --hash=sha256:cc\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "satisfies all 3 declared dependencies" in result.stdout


def test_rejects_the_exact_dependabot_bump_that_broke_ci(tmp_path: Path) -> None:
    """redis==8.1.0 cannot coexist with arq, and the lock must not claim it can."""
    result = _run(
        PYPROJECT,
        "redis==8.1.0 \\\n    --hash=sha256:aa\narq==0.28.0 \\\n    --hash=sha256:bb\n"
        "pytest==9.0.0 \\\n    --hash=sha256:cc\n",
        tmp_path,
    )
    assert result.returncode == 1
    assert "redis==8.1.0" in result.stdout
    assert "does not satisfy the declared" in result.stdout
    # The message has to name the fix, not just the fault.
    assert "pip-compile" in result.stdout


def test_rejects_a_declared_dependency_missing_from_the_lock(tmp_path: Path) -> None:
    result = _run(
        PYPROJECT,
        "redis==5.3.1 \\\n    --hash=sha256:aa\narq==0.28.0 \\\n    --hash=sha256:bb\n",
        tmp_path,
    )
    assert result.returncode == 1
    assert "pytest" in result.stdout
    assert "absent from constraints.txt" in result.stdout


def test_rejects_a_pin_outside_a_specifier_even_when_present(tmp_path: Path) -> None:
    result = _run(
        PYPROJECT,
        "redis==4.9.0 \\\n    --hash=sha256:aa\narq==0.28.0 \\\n    --hash=sha256:bb\n"
        "pytest==9.0.0 \\\n    --hash=sha256:cc\n",
        tmp_path,
    )
    assert result.returncode == 1
    assert "redis==4.9.0" in result.stdout


def test_normalises_names_so_the_check_is_not_defeated_by_spelling(tmp_path: Path) -> None:
    """`typing-extensions` in the lock satisfies `typing_extensions` in the manifest."""
    pyproject = PYPROJECT.replace('"arq>=0.26",', '"arq>=0.26",\n    "typing_extensions>=4",')
    result = _run(
        pyproject,
        "redis==5.3.1 \\\n    --hash=sha256:aa\narq==0.28.0 \\\n    --hash=sha256:bb\n"
        "pytest==9.0.0 \\\n    --hash=sha256:cc\n"
        "typing-extensions==4.15.0 \\\n    --hash=sha256:dd\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_committed_repository_state_passes_the_gate() -> None:
    """The gate must be green on the tree it ships with, read-only.

    Read-only matters: the step it replaces rewrote constraints.txt. This
    asserts the file is byte-identical before and after, so the check can never
    grade its own output again.
    """
    before = (REPO / "apps/api/constraints.txt").read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (REPO / "apps/api/constraints.txt").read_bytes() == before


@pytest.mark.parametrize(
    "declared, pinned, ok",
    [
        ("redis>=5.0,<6", "6.0.0", False),
        ("redis>=5.0,<6", "5.3.1", True),
        ("fastapi>=0.115", "0.115.0", True),
        ("fastapi>=0.115", "0.100.0", False),
    ],
)
def test_specifier_boundaries(declared: str, pinned: str, ok: bool, tmp_path: Path) -> None:
    name = declared.split(">")[0].split("<")[0]
    result = _run(
        f'[project]\nname = "demo"\nversion = "0.0.0"\ndependencies = ["{declared}"]\n',
        f"{name}=={pinned} \\\n    --hash=sha256:aa\n",
        tmp_path,
    )
    assert (result.returncode == 0) is ok, result.stdout + result.stderr
