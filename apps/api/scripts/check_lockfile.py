"""`constraints.txt` must be a faithful lock of `pyproject.toml`.

This replaces a check that could not fail. The previous version ran
`pip-compile --output-file constraints.txt` **in the checkout** -- overwriting
the very file it was meant to grade -- and then read that regenerated file back
to assert that every dependency named in `pyproject.toml` appears in it. A file
freshly compiled *from* `pyproject.toml` always contains every dependency named
in it, so the assertion was a tautology, and `CONTRIBUTING.md`'s promise that
"a stale lock cannot slip through" was false. It did not slip through because
of that step: it slipped through because a later `pip install` failed.

The concrete miss: Dependabot bumped `redis` to 8.1.0 in the lock while `arq`
(unchanged, and the reason redis is capped) requires `redis[hiredis]<6`. The
regenerated file never contradicted the committed one, the guardrails job
passed in 32 s, and five other jobs then died with `ResolutionImpossible`.

## What this checks, and what it deliberately does not

Checked here, deterministically and with no network:

  1. every dependency `pyproject.toml` declares is pinned in the lock;
  2. the pinned version satisfies the specifier `pyproject.toml` declares, so
     `redis==8.1.0` cannot sit under a declared `redis>=5.0,<6`.

Not checked here, on purpose:

  * that the lock is the *newest* resolvable set. Recompiling and diffing was
    tried and removed: pip-compile resolves floating transitives against
    whatever PyPI serves at that moment, so two clean resolves minutes apart
    legitimately differ and the gate failed on untouched, valid locks.
  * that transitive pins are mutually compatible. That invariant is proved by
    installing the lock (`pip install --require-hashes -r constraints.txt`),
    which every job that builds or tests the API already does -- and which is
    exactly the step that caught the redis/arq conflict.

So this gate is narrow, but what it asserts is true, deterministic, and able to
fail. Keep the promises in `CONTRIBUTING.md` aligned with that scope.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

try:
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion, Version
except ModuleNotFoundError:  # pragma: no cover - environment problem, not a lock problem
    print("::error::the 'packaging' library is required: python -m pip install packaging")
    raise SystemExit(2) from None

REPO = Path(__file__).resolve().parents[3]  # .../apps/api/scripts/... -> repo root

PIN = re.compile(r"^([A-Za-z0-9._-]+)==([^\s\\;]+)")

REGENERATE = (
    "python -m pip install pip-tools && cd apps/api && pip-compile "
    "--generate-hashes --allow-unsafe --extra dev --strip-extras pyproject.toml"
)


def declared_requirements(pyproject_path: Path) -> list[Requirement]:
    """Every requirement in `[project]`, extras included, as packaging objects."""
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]
    raw: list[str] = list(project.get("dependencies", []))
    for deps in project.get("optional-dependencies", {}).values():
        raw.extend(deps)

    parsed: list[Requirement] = []
    for line in raw:
        try:
            parsed.append(Requirement(line))
        except InvalidRequirement as exc:  # a broken manifest is its own failure
            print(f"::error file={pyproject_path}::unparseable requirement {line!r}: {exc}")
            raise SystemExit(1) from None
    return parsed


def pinned_versions(constraints_path: Path) -> dict[str, str]:
    """`name -> version` for every `name==version` line in a pip-compile lock."""
    pins: dict[str, str] = {}
    for line in constraints_path.read_text(encoding="utf-8").splitlines():
        match = PIN.match(line)
        if match:
            pins[canonicalize_name(match.group(1))] = match.group(2)
    return pins


def check(pyproject_path: Path, constraints_path: Path) -> list[str]:
    """Return one human-readable problem per violation; empty means the gate passes."""
    requirements = declared_requirements(pyproject_path)
    pins = pinned_versions(constraints_path)
    problems: list[str] = []

    for requirement in requirements:
        name = canonicalize_name(requirement.name)
        pinned = pins.get(name)
        if pinned is None:
            problems.append(f"{name} is declared in pyproject.toml but absent from constraints.txt")
            continue
        if requirement.specifier and not requirement.specifier.contains(pinned, prereleases=True):
            problems.append(
                f"{name}=={pinned} in constraints.txt does not satisfy the declared "
                f"{name}{requirement.specifier} in pyproject.toml"
            )
            continue
        try:
            Version(pinned)
        except InvalidVersion:
            problems.append(f"{name}=={pinned} in constraints.txt is not a valid version")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pyproject", type=Path, default=REPO / "apps/api/pyproject.toml")
    parser.add_argument("--constraints", type=Path, default=REPO / "apps/api/constraints.txt")
    args = parser.parse_args(argv)

    problems = check(args.pyproject, args.constraints)
    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        print(f"{len(problems)} lockfile problem(s). Regenerate with:\n  {REGENERATE}")
        return 1

    count = len(declared_requirements(args.pyproject))
    print(f"constraints.txt satisfies all {count} declared dependencies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
