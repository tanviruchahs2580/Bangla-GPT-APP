"""Dependency-floor regression tests.

The repository pins no lockfile, so a dependency floor is the only control on
what a fresh install resolves to. Two floors were too low to exclude vulnerable
releases: `pyjwt>=2.9` resolved to 2.13 (13 advisories) and `pypdf>=5.0` to 6.16
(8 advisories, in the parser that reads operator-supplied textbook PDFs).

These tests assert the floors, so a future downgrade cannot silently reopen the
range. They do not replace `pip-audit`, which CI runs on the resolved set.
"""

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


@pytest.fixture(scope="module")
def deps() -> dict[str, str]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]


def _spec(deps: dict[str, str], name: str) -> str:
    for entry in deps:
        if entry.split(">")[0].split("=")[0].split("[")[0].strip() == name:
            return entry
    raise AssertionError(f"{name} is not a declared dependency")


def test_pyjwt_floor_excludes_the_advisory_range(deps: dict[str, str]) -> None:
    """PYSEC-2026-4140..4152 affect PyJWT below 2.14/2.15."""
    spec = _spec(deps, "pyjwt")
    assert ">=2.15.0" in spec, (
        f"pyjwt floor is too low: {spec!r} resolves to releases with 13 known "
        "advisories. Raise the floor to the first patched release."
    )


def test_pypdf_floor_excludes_the_advisory_range(deps: dict[str, str]) -> None:
    """PYSEC-2026-4153..4160 affect pypdf below 6.17-6.19.

    This is the parser that extracts text from uploaded textbook PDFs, so the
    advisory surface is directly reachable.
    """
    spec = _spec(deps, "pypdf")
    assert ">=6.19.0" in spec, (
        f"pypdf floor is too low: {spec!r} resolves to releases with 8 known "
        "advisories in the PDF extraction path"
    )


def test_security_critical_deps_have_explicit_floors(deps: dict[str, str]) -> None:
    """Auth, crypto, DB driver and HTTP client floors must all be pinned up."""
    for name in ("pyjwt", "cryptography", "pypdf", "psycopg", "httpx", "redis"):
        spec = _spec(deps, name)
        assert ">=" in spec, f"{name} has no version floor: {spec!r}"
