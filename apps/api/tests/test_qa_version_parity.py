"""F-053: the reported version must track the release manifest.

``apps/api/pyproject.toml`` is the single source of truth (README: "Nothing
else may carry a version number"). The served OpenAPI version previously read
``config.py``'s hardcoded fallback ``"0.9.2"`` while the manifest said
``0.9.3``, so clients and operators could not tell what release was running.
These tests pin both directions: the ``Settings.version`` field follows the
installed distribution metadata when one exists, and the source-tree fallback
reads the manifest itself instead of a literal that drifts on every bump.
"""

from __future__ import annotations

import importlib.metadata
import json
import tomllib
from pathlib import Path

from bangla_gpt_api import config
from bangla_gpt_api.config import Settings

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]


def _pyproject_version() -> str:
    with (API_DIR / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_reported_version_matches_installed_metadata(monkeypatch) -> None:
    # A VERSION env var would override the field for the whole app; pin the
    # default rather than whatever the developer's shell exports.
    monkeypatch.delenv("VERSION", raising=False)
    assert Settings().version == importlib.metadata.version("bangla-gpt-api")


def test_fallback_reads_the_manifest_not_a_literal(monkeypatch) -> None:
    def _not_installed(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _not_installed)
    assert config._get_version() == _pyproject_version()


def test_web_package_json_mirrors_the_manifest() -> None:
    package_json = json.loads(
        (REPO_ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8")
    )
    assert package_json["version"] == _pyproject_version()
