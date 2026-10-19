"""Design-token drift scan for the web app (AUD-G-08 / G-01).

Two defects the audit found by hand are made mechanical here:

1. **Hard-coded colours outside the token layer.** ``apps/web/src/styles.css``
   declares every colour once in ``:root`` and ``[data-theme=...]``; any
   literal colour anywhere else (hex, ``rgb()``/``hsl()``) is drift, as is any
   literal colour in component code. Test files are excluded: they are
   fixtures, not rendered surfaces.

2. **Off-grid px values.** Outside the token blocks, a ``<n>px`` length counts
   as off-grid when it is not a multiple of the 4px spacing grid, not one of
   the px values the token layer itself declares (read from the file, so the
   scale cannot silently drift apart from the checker), and not one of the
   structural hairline widths in ``STRUCTURAL_PX`` (1px/2px/3px borders and
   focus rings).

Usage::

    python scripts/scan_design_tokens.py            # report, exit 0
    python scripts/scan_design_tokens.py --check    # ratchet vs baseline
    python scripts/scan_design_tokens.py --update-baseline

The ratchet baseline lives at
``apps/web/quality-baselines/design-tokens.json`` and may only be moved by a
commit that also drops one of the counts.

``--check`` exits 1 when a count exceeds the baseline. It cannot fail on the
current tree: the initial baseline is what this script measured at the commit
that introduced it (see the findings register, AUD-G-08).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB_SRC = REPO / "apps" / "web" / "src"
STYLES = WEB_SRC / "styles.css"
BASELINE = REPO / "apps" / "web" / "quality-baselines" / "design-tokens.json"

#: Hairline and focus-ring widths that are intentionally not on the 4px grid.
STRUCTURAL_PX = {1.0, 2.0, 3.0}

COLOUR_HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b")
COLOUR_FUNC = re.compile(r"\b(?:rgba?|hsla?)\(")
PX_VALUE = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)px\b")

#: Selectors whose blocks *are* the token layer (whole selector, not a prefix:
#: ``[data-theme="dark"] .card`` is a rule, not a token declaration block).
TOKEN_SELECTOR = re.compile(r"(:root|\[data-theme(?:=[^\]]*)?\])\s*$")

COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def blank_comments(text: str) -> str:
    """Replace CSS comments with spaces, keeping every offset identical."""
    return COMMENT.sub(lambda match: " " * len(match.group(0)), text)


def token_block_spans(css: str) -> list[tuple[int, int]]:
    """Character spans of the ``:root`` / ``[data-theme=...]`` declaration blocks."""
    clean = blank_comments(css)
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"([^{}]*)\{", clean):
        if not TOKEN_SELECTOR.search(match.group(1)):
            continue
        depth = 1
        index = match.end()
        while index < len(clean) and depth:
            if clean[index] == "{":
                depth += 1
            elif clean[index] == "}":
                depth -= 1
            index += 1
        spans.append((match.start(), index))
    return spans


def outside(spans: list[tuple[int, int]], total: int) -> list[bool]:
    inside = [False] * total
    for start, end in spans:
        for index in range(start, min(end, total)):
            inside[index] = True
    return inside


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def scan_colours(path: Path, css: str | None = None) -> list[str]:
    text = css if css is not None else path.read_text(encoding="utf-8")
    allowed = (
        outside(token_block_spans(text), len(text)) if css is not None else [False] * len(text)
    )
    findings = []
    for regex in (COLOUR_HEX, COLOUR_FUNC):
        for match in regex.finditer(text):
            if css is not None and allowed[match.start()]:
                continue
            findings.append(f"{path.name}:{line_of(text, match.start())}: {match.group(0)}")
    return findings


def token_px_values(css: str) -> set[float]:
    spans = token_block_spans(css)
    values: set[float] = set()
    for start, end in spans:
        for match in PX_VALUE.finditer(css, start, end):
            values.add(float(match.group(1)))
    return values


def scan_px(css: str, declared: set[float]) -> tuple[list[str], Counter[str]]:
    allowed = outside(token_block_spans(css), len(css))
    findings: list[str] = []
    histogram: Counter[str] = Counter()
    for match in PX_VALUE.finditer(css):
        if allowed[match.start()]:
            continue
        value = float(match.group(1))
        if value % 4 == 0 or value in declared or value in STRUCTURAL_PX or value == 0:
            continue
        findings.append(f"styles.css:{line_of(css, match.start())}: {match.group(0)}")
        histogram[f"{value:g}px"] += 1
    return findings, histogram


def source_files() -> list[Path]:
    files = []
    for path in sorted(WEB_SRC.rglob("*")):
        name = path.name
        if path.suffix not in {".ts", ".tsx", ".css"} or not path.is_file():
            continue
        if ".test." in name or ".spec." in name or path.parent.name == "test":
            continue
        files.append(path)
    return files


def collect() -> dict:
    css = STYLES.read_text(encoding="utf-8")
    declared = token_px_values(css)
    colours: dict[str, list[str]] = {}
    for path in source_files():
        if path == STYLES:
            found = scan_colours(path, css)
        else:
            found = scan_colours(path)
        if found:
            colours[path.relative_to(REPO).as_posix()] = found
    px_findings, histogram = scan_px(css, declared)
    return {
        "hardcoded_colours": {
            "count": sum(len(v) for v in colours.values()),
            "by_file": {k: len(v) for k, v in colours.items()},
            "examples": [item for v in colours.values() for item in v][:20],
        },
        "off_grid_px": {
            "count": len(px_findings),
            "common_values": dict(histogram.most_common(15)),
            "examples": px_findings[:20],
        },
    }


def print_report(result: dict) -> None:
    colours = result["hardcoded_colours"]
    px = result["off_grid_px"]
    print(f"hard-coded colours outside the token layer: {colours['count']}")
    for path, count in sorted(colours["by_file"].items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {path}")
    print(f"off-grid px values in styles.css: {px['count']}")
    for value, count in list(px["common_values"].items())[:8]:
        print(f"  {count:4d}x {value}")
    for example in px["examples"][:8]:
        print(f"    {example}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="ratchet against the baseline")
    parser.add_argument("--update-baseline", action="store_true", help="rewrite the baseline file")
    args = parser.parse_args()

    result = collect()
    print_report(result)

    if args.update_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"baseline written to {BASELINE.relative_to(REPO).as_posix()}")
        return 0

    if not args.check:
        return 0

    if not BASELINE.exists():
        print(f"no baseline at {BASELINE.relative_to(REPO).as_posix()}; run --update-baseline")
        return 1
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    regressions = []
    for key, label in (
        ("hardcoded_colours", "hard-coded colours"),
        ("off_grid_px", "off-grid px values"),
    ):
        now = result[key]["count"]
        was = baseline[key]["count"]
        if now > was:
            regressions.append(f"{label}: {was} -> {now}")
        elif now < was:
            print(f"{label}: {was} -> {now} (baseline can be tightened)")
    if regressions:
        for line in regressions:
            print(f"REGRESSION: {line}")
        return 1
    print("design-token ratchet: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
