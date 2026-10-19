#!/usr/bin/env python
"""Enforce the Bangla terminology glossary (AUD-G-05 / G-25).

The glossary in ``docs/i18n-glossary.md`` is the single source of truth for
product terminology. This check reads its tables and inspects the Bangla UI
dictionary, so an unapproved variant cannot come back through a copy edit:

* every ``avoid`` form that appears in a dictionary value is an error;
* an approved term that no string uses is reported as a warning (the glossary
  may legitimately run ahead of the copy);
* the ``Open decisions`` table is reported as ``pending`` - a real
  inconsistency awaiting a native speaker, which never fails the build.

Run it from CI and from the pre-commit hook:

    python scripts/check_glossary.py            # exits non-zero on violations
    python scripts/check_glossary.py --report   # always exits 0, prints all
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GLOSSARY = REPO / "docs" / "i18n-glossary.md"
I18N = REPO / "apps" / "web" / "src" / "i18n.ts"

ROW = re.compile(r"^\|(?P<cells>.+)\|\s*$", re.M)
ENTRY = re.compile(
    r'^\s{2}([A-Za-z_][A-Za-z0-9_]*):\s*"((?:[^"\\]|\\.)*)",?\s*$', re.M
)


class GlossaryError(Exception):
    """A malformed glossary: the check must not silently pass."""


def section(text: str, title: str) -> str:
    start = text.index(title)
    rest = text[start + len(title):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def clean(cell: str) -> str:
    """Drop markdown emphasis and parenthetical asides from a table cell."""
    cell = re.sub(r"\*|`", "", cell)
    return re.sub(r"\([^)]*\)", "", cell).strip()


def parse_terms(text: str) -> list[tuple[str, str, list[str]]]:
    rows: list[tuple[str, str, list[str]]] = []
    for match in ROW.finditer(section(text, "## Terms")):
        cells = [c.strip() for c in match.group("cells").split("|")]
        if len(cells) != 4 or cells[0] in {"English", "---"} or set(cells[0]) <= {"-"}:
            continue
        english, approved, avoid, _keys = cells
        avoid_forms = [clean(f) for f in avoid.split(",") if clean(f)]
        rows.append((english, clean(approved), avoid_forms))
    if not rows:
        raise GlossaryError("no term rows found in docs/i18n-glossary.md")
    return rows


def parse_pending(text: str) -> list[tuple[str, str]]:
    """(primary form, pending alternate) from the Open decisions table."""
    rows: list[tuple[str, str]] = []
    body = section(text, "## Open decisions")
    for match in ROW.finditer(body):
        cells = [c.strip() for c in match.group("cells").split("|")]
        if len(cells) != 3 or cells[0] in {"Concept"} or set(cells[0]) <= {"-"}:
            continue
        concept, in_use, _where = cells
        parts = re.split(r"\s+vs\s+", in_use, maxsplit=1)
        if len(parts) == 2:
            rows.append((clean(parts[0]), clean(parts[1])))
    return rows


def dict_entries() -> list[tuple[int, str, str]]:
    """(line, key, value) for the Bangla dictionary."""
    text = I18N.read_text(encoding="utf-8")
    start = text.index("const bn = {")
    end = text.index("const en: Dict = {", start)
    block = text[start:end]
    base_line = text[:start].count("\n") + 1
    return [
        (base_line + block[: m.start()].count("\n"), m.group(1), m.group(2))
        for m in ENTRY.finditer(block)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="always exit 0")
    args = parser.parse_args()

    text = GLOSSARY.read_text(encoding="utf-8")
    try:
        terms = parse_terms(text)
    except GlossaryError as exc:
        print(f"glossary error: {exc}", file=sys.stderr)
        return 1

    # The check must not be able to flag approved copy by accident.
    for english, approved, avoid_forms in terms:
        for form in avoid_forms:
            if form in approved:
                print(
                    f"glossary error: avoid form {form!r} is a substring of the "
                    f"approved term for {english!r} ({approved!r})",
                    file=sys.stderr,
                )
                return 1

    entries = dict_entries()
    rel = I18N.relative_to(REPO).as_posix()
    errors: list[str] = []
    warnings: list[str] = []

    for english, approved, avoid_forms in terms:
        for line, key, value in entries:
            for form in avoid_forms:
                if form in value:
                    errors.append(
                        f"{rel}:{line} [{key}] {english}: unapproved form "
                        f"{form!r} in {value!r} (use {approved!r})"
                    )
        if not any(approved in value for _line, _key, value in entries):
            warnings.append(
                f"glossary: approved term for {english!r} ({approved!r}) is not "
                "used by any dictionary value"
            )

    pending: list[str] = []
    for primary, alternate in parse_pending(text):
        hits = [key for _line, key, value in entries if alternate in value]
        if hits:
            pending.append(
                f"pending: {primary!r} vs {alternate!r} - {alternate!r} still "
                f"used by {', '.join(sorted(set(hits)))}"
            )

    for line in warnings:
        print(f"warning: {line}")
    for line in pending:
        print(f"{line}")
    for line in errors:
        print(f"::error::{line}")
    print(
        f"glossary: {len(terms)} terms, {len(entries)} dictionary values, "
        f"{len(errors)} violations, {len(warnings)} warnings, {len(pending)} pending"
    )
    if args.report:
        return 0
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
