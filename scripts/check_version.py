"""Single-source version check (audit finding AUD-JK-12 / work item J-11).

The version is currently hardcoded in several files. This script defines the
single source of truth as ``apps/api/pyproject.toml`` ``[project].version`` and
fails (exit 1) if any other file that states a version disagrees — including
the ``config.py`` fallback constant, the web package + lock, the README
"Current version" line, the deployment guide's image tags and the newest
released CHANGELOG heading.

Read-only. Run from anywhere:

    python scripts/check_version.py
    python scripts/check_version.py --tag      # also compare the latest git tag

CI wiring is intentionally not in this change (workflow files belong to the
ci owner); the handoff lives in .audit/handoffs/ef-from-jk.md. A pytest in
apps/api/tests/test_jk_version_sources.py runs this check in the normal suite,
so a drift fails CI today without touching a workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(os.environ.get("CHECK_VERSION_ROOT") or Path(__file__).resolve().parents[1])
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def source_version() -> str:
    """The one source of truth: apps/api/pyproject.toml [project].version."""
    data = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _regex_first(path: Path, pattern: str) -> str | None:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def collect() -> list[tuple[str, str, str | None]]:
    """Return (label, file, version-or-None) for every place that states one."""
    rows: list[tuple[str, str, str | None]] = []

    rows.append(("pyproject [project]", "apps/api/pyproject.toml", source_version()))

    rows.append(
        (
            "config.py fallback constant",
            "apps/api/src/bangla_gpt_api/config.py",
            _regex_first(
                ROOT / "apps/api/src/bangla_gpt_api/config.py",
                r'must track pyproject version\)\.\s*\n\s*return "(\d+\.\d+\.\d+)"',
            ),
        )
    )

    package_json = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    rows.append(("web package.json", "apps/web/package.json", package_json.get("version")))

    lock = json.loads((ROOT / "apps/web/package-lock.json").read_text(encoding="utf-8"))
    rows.append(("package-lock root", "apps/web/package-lock.json", lock.get("version")))
    rows.append(
        (
            "package-lock packages['']",
            "apps/web/package-lock.json",
            (lock.get("packages") or {}).get("", {}).get("version"),
        )
    )

    rows.append(
        (
            "README current version",
            "README.md",
            _regex_first(ROOT / "README.md", r"Current version:\s*\**(\d+\.\d+\.\d+)"),
        )
    )

    rows.append(
        (
            "deployment guide image tag",
            "docs/operations/PRODUCTION_DEPLOYMENT.md",
            _regex_first(
                ROOT / "docs/operations/PRODUCTION_DEPLOYMENT.md",
                r"api:v(\d+\.\d+\.\d+)",
            ),
        )
    )

    rows.append(
        (
            "CHANGELOG newest released heading",
            "CHANGELOG.md",
            _regex_first(ROOT / "CHANGELOG.md", r"^## v(\d+\.\d+\.\d+)"),
        )
    )

    return rows


def latest_tag() -> str | None:
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.removeprefix("v")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        action="store_true",
        help="also compare the version with the latest git tag (skipped by default: "
        "a release tag is an owner action and tags legitimately lag HEAD)",
    )
    args = parser.parse_args(argv)

    expected = source_version()
    failures: list[str] = []
    print(f"source of truth: apps/api/pyproject.toml [project].version = {expected}")
    for label, path, found in collect():
        if found is None:
            failures.append(f"{label}: no version found in {path}")
            print(f"  MISSING  {label:34s} {path}")
        elif found != expected:
            failures.append(f"{label}: {found} != {expected} ({path})")
            print(f"  DRIFT    {label:34s} {path} -> {found}")
        else:
            print(f"  ok       {label:34s} {path}")

    if args.tag:
        tag = latest_tag()
        if tag is None:
            print("  (no git tag found; skipped)")
        elif tag != expected:
            failures.append(f"latest tag v{tag} != {expected} (tags are an owner action)")
            print(f"  DRIFT    latest git tag            -> v{tag}")
        else:
            print(f"  ok       latest git tag            v{tag}")

    if failures:
        print(f"\nFAIL: {len(failures)} place(s) disagree with the source of truth")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("\nOK: every recorded version matches the source of truth")
    return 0


if __name__ == "__main__":
    sys.exit(main())
