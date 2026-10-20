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
   focus rings). Two kinds of px text are not rendered values and are exempt:

   * **comments.** The scan blanks comments before looking for lengths, so a
     prose mention ("replaces the 5px dot") is not a finding. Every other
     check in this file already worked on comment-blanked text; the px scan
     reading raw text was an oversight, and it made the count depend on
     wording rather than on the stylesheet.
   * **media-query conditions** (``@media (max-width: 899px)``). A CSS custom
     property is invalid inside a media condition -- ``@media (max-width:
     var(--bp))`` never matches -- so a breakpoint cannot be expressed as a
     token at all. They are a structural class of their own, like
     ``STRUCTURAL_PX``, and are listed separately in the report.

3. **Self-referential token cycles.** ``--sheen-12: var(--sheen-12)`` is valid
   CSS syntax that makes the property *guaranteed-invalid* at computed-value
   time: every declaration that reads it silently falls back to the inherited
   or initial value. A batch of these (31 of them, found by hand in wave 2)
   is why the modal scrim, the hero glow and ~10 shadows quietly stopped
   painting. The cycle detector makes that mechanical: it builds the
   ``var()`` reference graph of every declaration block and reports direct
   self-references *and* transitive cycles (``--a: var(--b)`` +
   ``--b: var(--a)``), which is a check no linter in this repo performs.
   Any cycle is a failure in ``--check`` -- unlike the two counts above, this
   one is an absolute, not a ratchet.

Usage::

    python scripts/scan_design_tokens.py            # report, exit 0
    python scripts/scan_design_tokens.py --check    # ratchet + cycle gate vs baseline
    python scripts/scan_design_tokens.py --update-baseline
    python scripts/scan_design_tokens.py --self-test  # exercise the detectors

The ratchet baseline lives at
``apps/web/quality-baselines/design-tokens.json`` and may only be moved by a
commit that also drops one of the counts.

``--check`` exits 1 when a count exceeds the baseline, or when any token cycle
exists. ``--self-test`` runs the three detectors against small fixtures plus
the real stylesheet, so the cycle detector itself has a test that fails when
it stops detecting.
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

#: ``@media`` up to (not including) its opening brace: the condition itself.
MEDIA_PRELUDE = re.compile(r"@media\b[^{]*")

#: A custom-property declaration and the ``var()`` references in its value.
CUSTOM_PROP_DECL = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;{}]*)")
VAR_REF = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)")


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


def media_query_spans(css: str) -> list[tuple[int, int]]:
    """Character spans of every ``@media`` condition (its prelude).

    Custom properties are invalid in a media condition, so a breakpoint cannot
    be a token; these values are exempt from the grid and listed separately.
    """
    clean = blank_comments(css)
    return [(match.start(), match.end()) for match in MEDIA_PRELUDE.finditer(clean)]


def declaration_blocks(css: str) -> list[tuple[int, str]]:
    """``(offset, body)`` for every ``{...}`` block, nested blocks blanked out.

    A cycle is scoped to the block that declares it: two properties in
    different blocks never resolve against each other, so the graph must not
    join them (that would invent cycles that cannot happen).
    """
    clean = blank_comments(css)
    spans: list[tuple[int, int]] = []
    stack: list[int] = []
    for index, char in enumerate(clean):
        if char == "{":
            stack.append(index)
        elif char == "}" and stack:
            spans.append((stack.pop() + 1, index))
    blocks: list[tuple[int, str]] = []
    for start, end in spans:
        body = list(clean[start:end])
        for inner_start, inner_end in spans:
            if inner_start >= start and inner_end <= end and inner_start != start:
                for index in range(inner_start - start, inner_end - start):
                    if 0 <= index < len(body):
                        body[index] = " "
        blocks.append((start, "".join(body)))
    return blocks


def cycle_findings(css: str, name: str = "styles.css") -> list[str]:
    """Custom properties that resolve in terms of themselves.

    Direct (``--a: var(--a)``) and transitive (``--a: var(--b)`` with
    ``--b: var(--a)``) cycles are both guaranteed-invalid CSS: the property
    computes to the inherited/initial value, so whatever paints with it
    silently stops painting. Reported one line per cycle, in declaration
    order, with the line of the first declaration in the cycle.
    """
    findings: list[str] = []
    for offset, body in declaration_blocks(css):
        decls: dict[str, list[str]] = {}
        lines: dict[str, int] = {}
        for match in CUSTOM_PROP_DECL.finditer(body):
            prop, value = match.group(1), match.group(2)
            lines.setdefault(prop, line_of(css, offset + match.start()))
            refs = decls.setdefault(prop, [])
            refs.extend(ref for ref in VAR_REF.findall(value) if ref not in refs)
        for prop in decls:
            if prop in decls[prop]:
                findings.append(
                    f"{name}:{lines[prop]}: cycle --{prop[2:]} -> --{prop[2:]}"
                )
        reported: set[frozenset[str]] = set()
        for start in decls:
            # Depth-first walk of the reference graph; every path that comes
            # back to its start is a cycle. Paths never repeat a node, so the
            # cycle is exactly ``path`` and one set of members is reported
            # once no matter which member it was entered from.
            stack: list[tuple[str, list[str]]] = [(start, [start])]
            while stack:
                node, path = stack.pop()
                for ref in decls.get(node, []):
                    if ref == start:
                        if len(path) < 2 or frozenset(path) in reported:
                            continue  # direct self-reference: reported above
                        reported.add(frozenset(path))
                        findings.append(
                            f"{name}:{lines[start]}: cycle "
                            + " -> ".join(f"--{item[2:]}" for item in path + [start])
                        )
                    elif ref in decls and ref not in path:
                        stack.append((ref, path + [ref]))
    return findings


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


def scan_px(css: str, declared: set[float]) -> tuple[list[str], Counter[str], list[str]]:
    """Off-grid lengths outside the token blocks, comments and media conditions.

    Returns the findings, their value histogram, and the media-query
    breakpoints that are exempt by construction (reported for review, never
    silently dropped).
    """
    clean = blank_comments(css)
    media = media_query_spans(css)
    allowed = outside(token_block_spans(css) + media, len(clean))
    findings: list[str] = []
    histogram: Counter[str] = Counter()
    for match in PX_VALUE.finditer(clean):
        if allowed[match.start()]:
            continue
        value = float(match.group(1))
        if value % 4 == 0 or value in declared or value in STRUCTURAL_PX or value == 0:
            continue
        findings.append(f"styles.css:{line_of(clean, match.start())}: {match.group(0)}")
        histogram[f"{value:g}px"] += 1
    breakpoints = sorted({match.group(0) for span in media for match in PX_VALUE.finditer(clean, *span)})
    return findings, histogram, breakpoints


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
    px_findings, histogram, breakpoints = scan_px(css, declared)
    cycles = cycle_findings(css)
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
            "media_breakpoints": breakpoints,
        },
        "token_cycles": {"count": len(cycles), "examples": cycles[:20]},
    }


def print_report(result: dict) -> None:
    colours = result["hardcoded_colours"]
    px = result["off_grid_px"]
    cycles = result["token_cycles"]
    print(f"hard-coded colours outside the token layer: {colours['count']}")
    for path, count in sorted(colours["by_file"].items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {path}")
    print(f"off-grid px values in styles.css: {px['count']}")
    for value, count in list(px["common_values"].items())[:8]:
        print(f"  {count:4d}x {value}")
    for example in px["examples"][:8]:
        print(f"    {example}")
    if px.get("media_breakpoints"):
        print(
            "  exempt (media conditions; var() is invalid there): "
            + ", ".join(px["media_breakpoints"])
        )
    print(f"self-referential token cycles: {cycles['count']}")
    for example in cycles["examples"][:8]:
        print(f"    {example}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="ratchet against the baseline")
    parser.add_argument("--update-baseline", action="store_true", help="rewrite the baseline file")
    parser.add_argument("--self-test", action="store_true", help="exercise the detectors")
    args = parser.parse_args()

    if args.self_test:
        print("design-token scan self-test")
        return self_test()

    result = collect()
    print_report(result)

    if args.update_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n": a data file committed to the repo must not change shape
        # with the platform that regenerated it (Windows text mode would write
        # CRLF, turning every unrelated run into a whole-file diff).
        with BASELINE.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(result, indent=2) + "\n")
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
    # Cycles are an absolute gate, not a ratchet: one is one too many, because
    # a cyclic property computes to the inherited value and stops painting.
    cycles = result["token_cycles"]
    if cycles["count"]:
        for line in cycles["examples"]:
            print(f"REGRESSION: token cycle: {line}")
        return 1
    if regressions:
        for line in regressions:
            print(f"REGRESSION: {line}")
        return 1
    print(f"self-referential token cycles: 0 (of {baseline.get('token_cycles', {}).get('count', '?')} in the baseline)")
    print("design-token ratchet: OK")
    return 0


# ── self-test ─────────────────────────────────────────────────────────────
#: Fixtures the detector must get right. ``expected`` is the number of cycles
#: each one contains; the last case is the real stylesheet, which must stay at
#: zero. A detector that stops detecting fails here, which is the point: the
#: 31 cycles of wave 2 were found by hand because nothing checked.
CYCLE_FIXTURES: list[tuple[str, str, int]] = [
    (
        "direct self-reference",
        ":root { --sheen-12: var(--sheen-12); }",
        1,
    ),
    (
        "transitive cycle (two properties)",
        ":root { --a: var(--b); --b: var(--a); }",
        1,
    ),
    (
        "transitive cycle (three properties)",
        ":root { --a: var(--b); --b: var(--c); --c: var(--a); }",
        1,
    ),
    (
        "self-reference inside a longer value",
        ":root { --scrim: 0 0 0 100px var(--scrim); }",
        1,
    ),
    (
        "alias chain, no cycle",
        ":root { --elev-1: var(--shadow-a); --shadow-a: var(--shadow-b); --shadow-b: 0 1px 2px black; }",
        0,
    ),
    (
        "cycle in a nested @media block is found",
        "@media (max-width: 899px) { :root { --pad: var(--pad); } }",
        1,
    ),
    (
        "same name in two blocks is not a cycle",
        ":root { --a: var(--b); } [data-theme='dark'] { --b: var(--a); }",
        0,
    ),
    (
        "cycle inside a comment is not code",
        ":root { /* --a: var(--a); */ --a: 4px; }",
        0,
    ),
]


def self_test() -> int:
    failures = 0
    for label, fixture, expected in CYCLE_FIXTURES:
        found = len(cycle_findings(fixture, "fixture"))
        status = "ok" if found == expected else "FAIL"
        if found != expected:
            failures += 1
        print(f"  [{status}] {label}: {found} cycle(s), expected {expected}")

    # The px scan must not read prose or breakpoints as lengths.
    fixture = "/* the 5px dot */ @media (max-width: 899px) { .a { gap: 5px; } }"
    findings, _, breakpoints = scan_px(fixture, set())
    px_ok = findings == ["styles.css:1: 5px"] and breakpoints == ["899px"]
    print(
        f"  [{'ok' if px_ok else 'FAIL'}] px scan skips comments and media "
        f"conditions: findings={findings} breakpoints={breakpoints}"
    )
    failures += 0 if px_ok else 1

    real = cycle_findings(STYLES.read_text(encoding="utf-8"))
    print(f"  [{'ok' if not real else 'FAIL'}] styles.css: {len(real)} cycle(s)")
    failures += 0 if not real else 1

    print("self-test: OK" if not failures else f"self-test: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
