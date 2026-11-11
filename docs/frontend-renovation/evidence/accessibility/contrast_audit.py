"""
Reproducible WCAG contrast audit for Bangla GPT tokens.

Run from anywhere:

    <python> docs/frontend-renovation/evidence/accessibility/contrast_audit.py

Exit code 1 means at least one asserted pair is below its required threshold.

Two things this script does deliberately, both learned the hard way:

1. It resolves `apps/web/src/styles.css` relative to THIS FILE, not the working
   directory. The first version used a relative path and silently crashed with
   FileNotFoundError when invoked from `apps/web` -- a red gate for the wrong
   reason is worse than no gate.
2. It reads the values the stylesheet ACTUALLY declares rather than restating
   them. The first version re-implemented `.ring`'s track as
   `color-mix(--line 70%)`. After the track was changed to `--line-strong` the
   script still measured the old formula, so it kept reporting a failure that
   no longer existed. A measurement that does not read the artefact is not a
   measurement of the artefact.

Why this file exists at all: `apps/web/src/test/contrastTokens.test.ts` and
`formControlBoundary.test.ts` used to locate their token block with
`css.indexOf(":root {")`, which resolves to the FIRST block only. The two later
token blocks were invisible to every ratio computation in the repository. This
script parses ALL blocks, which is what surfaced the original findings.
"""

import re
import sys
from pathlib import Path


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "apps" / "web" / "src" / "styles.css").is_file():
            return parent
    raise SystemExit(
        "could not locate apps/web/src/styles.css from " + str(Path(__file__).resolve())
    )


CSS_PATH = repo_root() / "apps" / "web" / "src" / "styles.css"


def mask_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), css, flags=re.S)


# ---------------------------------------------------------------- colour math
def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb) -> float:
    r, g, b = (_lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def hx(h: str):
    h = h.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"not a 6-digit hex: {h!r}")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def over_alpha(fg, alpha: float, bg):
    """Composite `fg` at `alpha` over `bg` (both opaque RGB)."""
    return tuple(round(alpha * f + (1 - alpha) * b) for f, b in zip(fg, bg))


def mix(a, b, pct: float):
    """`color-mix(in srgb, A pct%, B)` -> pct of A, remainder B."""
    return tuple(round(pct * a[i] + (1 - pct) * b[i]) for i in range(3))


# ------------------------------------------------------------ token extraction
def parse_all_blocks(css: str):
    """{theme: {token: raw_value}} merging EVERY block per theme, in order."""
    out = {"light": {}, "dark": {}}
    body = mask_comments(css)
    for m in re.finditer(r"(:root|\[data-theme=\"dark\"\])\s*\{", body):
        theme = "light" if m.group(1) == ":root" else "dark"
        i, depth = m.end(), 1
        while i < len(body) and depth:
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
            i += 1
        for d in re.finditer(r"--([a-z0-9-]+)\s*:\s*([^;]+);", body[m.end() : i - 1]):
            out[theme][d.group(1)] = d.group(2).strip()
    return out


def resolve(tokens, name, seen=None):
    """Resolve `var(--x)` chains to a concrete value."""
    seen = seen or set()
    if name in seen:
        raise ValueError(f"circular token reference: {name}")
    raw = tokens[name]
    m = re.fullmatch(r"var\(\s*--([a-z0-9-]+)\s*\)", raw)
    if m:
        return resolve(tokens, m.group(1), seen | {name})
    return raw


def last_rule_body(css: str, selector: str) -> str:
    """Body of the LAST rule whose selector list contains `selector` as a member."""
    bodies = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", mask_comments(css)):
        members = [s.strip() for s in m.group(1).split(",")]
        if selector in members:
            bodies.append(m.group(2))
    if not bodies:
        raise SystemExit(f"no rule for {selector} in {CSS_PATH}")
    return bodies[-1]


def split_top_level(text: str) -> list:
    """Split on commas that are not inside parentheses."""
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [s.strip() for s in out if s.strip()]


def gradient_stops(args: str) -> list:
    """Colour stops of a `conic-gradient(...)`, minus any `from <angle>` prelude."""
    args = re.sub(
        r"^\s*from\s+[-+\d.]+(?:deg|rad|turn|grad)\s*,?", "", args, flags=re.I
    )
    return split_top_level(args)


def declared_colour(expr: str, tokens, backdrop):
    """Resolve a CSS colour expression to RGB as it renders on `backdrop`.

    Handles `var(--x)`, a hex literal, and `color-mix(in srgb, A p%, transparent)`
    -- the last one composited over `backdrop`, which is what a transparent mix
    stop actually reveals.
    """
    expr = expr.strip()
    var = re.fullmatch(r"var\(\s*--([a-z0-9-]+)\s*\)", expr)
    if var:
        return hx(resolve(tokens, var.group(1)))
    if re.fullmatch(r"#[0-9a-fA-F]{6}", expr):
        return hx(expr)
    cm = re.fullmatch(
        r"color-mix\(\s*in srgb\s*,\s*var\(\s*--([a-z0-9-]+)\s*\)\s*([\d.]+)%\s*,\s*transparent\s*\)",
        expr,
    )
    if cm:
        return mix(hx(resolve(tokens, cm.group(1))), backdrop, float(cm.group(2)) / 100)
    raise SystemExit(f"unhandled colour expression: {expr!r}")


# ------------------------------------------------------------------- findings
def main() -> int:
    css = CSS_PATH.read_text(encoding="utf-8")
    tok = parse_all_blocks(css)
    # `parse_all_blocks` returns each theme's OWN declarations, so a token that
    # exists only in :root (like --placeholder, which is theme-invariant by
    # design) is absent from the dark map. Resolution has to model the cascade:
    # dark inherits light, then overrides.
    light = tok["light"]
    dark = {**light, **tok["dark"]}
    light.setdefault("white", "#ffffff")

    failures = []
    print(f"styles.css: {CSS_PATH}")
    print(f"parsed {len(light)} light tokens, {len(dark)} dark overrides\n")

    # --- F1: hero prompt placeholder ---------------------------------------
    # .hero .home-prompt .input paints a literal nearly-opaque white fill over
    # --grad-hero in BOTH themes, so the placeholder must be theme-invariant and
    # clear 4.5:1 against that fill.
    ph = hx(resolve(light, "hero-placeholder"))
    hero_stops = [
        resolve(light, "brand-ink"),
        resolve(light, "brand"),
        resolve(light, "brand-strong"),
    ]
    print("F1  hero prompt placeholder (need >= 4.5:1 text)")
    worst = 10.0
    for stop in hero_stops:
        fill = over_alpha((255, 255, 255), 0.96, hx(stop))
        r = ratio(ph, fill)
        worst = min(worst, r)
        print(f"      {resolve(light, 'hero-placeholder'):<8} over rgba(255,255,255,.96)"
              f" / {stop:<9} = {r:5.2f}")
    if worst < 4.5:
        failures.append(f"hero placeholder {worst:.2f}:1 < 4.5:1")

    # --- F2: progress-ring track, read from the stylesheet ------------------
    print("\nF2  progress-ring track (need >= 3:1 non-text)")
    for theme, toks in (("light", light), ("dark", dark)):
        card = hx(resolve(toks, "card"))
        body = last_rule_body(css, ".ring")
        grad = re.search(r"conic-gradient\((.*?)\)\s*;", body, re.S)
        if not grad:
            raise SystemExit("could not find a conic-gradient in the last .ring rule")
        stops = gradient_stops(grad.group(1))
        # The track is the final stop: everything before it is the value arc.
        track_expr = re.sub(
            r"\s+calc\(.*\)\s*$|\s+[\d.]+%\s*$", "", stops[-1]
        ).strip()
        track = declared_colour(track_expr, toks, card)
        r = ratio(track, card)
        print(f"      {theme:<5} {track_expr:<22} over --card = {r:5.2f}")
        if r < 3.0:
            failures.append(f"{theme} ring track {r:.2f}:1 < 3:1")

    # --- F3: semantic label pairs ------------------------------------------
    print("\nF3  semantic label pairs previously covered by no guard (need >= 4.5:1)")
    for label, fg, bg in [
        ("ok on ok-soft", "ok", "ok-soft"),
        ("warn on warn-soft", "warn", "warn-soft"),
        ("danger on danger-soft", "danger", "danger-soft"),
        ("teal-strong on teal-soft", "teal-strong", "teal-soft"),
        ("ai on ai-soft", "ai", "ai-soft"),
        ("muted on card", "muted", "card"),
        ("muted on bg-elev", "muted", "bg-elev"),
        ("muted on card-2", "muted", "card-2"),
        ("muted on bg", "muted", "bg"),
        ("placeholder on card/2/elev/bg", "placeholder", None),
    ]:
        if bg is None:
            pairs = [("card", "card"), ("card-2", "card-2"), ("bg-elev", "bg-elev"), ("bg", "bg")]
        else:
            pairs = [(bg, bg)]
        for name, key in pairs:
            rl = ratio(hx(resolve(light, fg)), hx(resolve(light, key)))
            rd = ratio(hx(resolve(dark, fg)), hx(resolve(dark, key)))
            flag = ""
            if rl < 4.5 or rd < 4.5:
                flag = "  <-- FAIL"
                failures.append(f"{label} on {name} light={rl:.2f} dark={rd:.2f}")
            print(
                f"      --{fg:<13} on --{name:<8} light={rl:6.2f}  dark={rd:6.2f}{flag}"
            )

    # --- F4: known limits, reported but NOT asserted ------------------------
    # These are recorded for the owner rather than pinned as passing: the fix
    # is a design decision, not an unambiguous correction. See RISK-REGISTER
    # R-15 and R-16.
    print("\nF4  known limits (reported, not asserted -- owner decisions)")
    for theme, toks in (("light", light), ("dark", dark)):
        card = hx(resolve(toks, "card"))
        body = last_rule_body(css, ".ring")
        grad = re.search(r"conic-gradient\((.*?)\)\s*;", body, re.S)
        stops = gradient_stops(grad.group(1))
        arc = declared_colour(stops[0].split()[0], toks, card)
        track_expr = re.sub(r"\s+calc\(.*\)\s*$|\s+[\d.]+%\s*$", "", stops[-1]).strip()
        track = declared_colour(track_expr, toks, card)
        print(f"      {theme:<5} ring arc vs track = {ratio(arc, track):5.2f}  (R-15)")

    print()
    if failures:
        print("RESULT: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS -- every asserted pair meets its threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
