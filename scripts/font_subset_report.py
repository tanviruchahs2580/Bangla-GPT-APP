"""S6.6: measure the payload reduction from webfont subsetting.

Builds the app UI charset by scanning every source file the web bundle
ships (TS/TSX/CSS), unions it with the full Bangla block + annotation
marks (LLM answers are open-ended, so the Bangla block must stay whole)
and common math/typographic symbols, then subsets:

1. the full Noto Sans Bengali TTF (130 KB source-of-truth font) to that
   charset -> woff2, and
2. each UI woff2 already shipped in apps/web/dist -- re-subsetting them
   shows whether fontsource's per-script split leaves further headroom.

Prints a bytes-before/after table. Run from apps/web:

    ../..//.ven*/Scripts/python -X utf8 ../../scripts/font_subset_report.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "apps" / "web"
FULL_TTF = REPO / "apps" / "api" / "src" / "bangla_gpt_api" / "data" / "fonts" / (
    "NotoSansBengali-Regular.ttf"
)

# Ranges the app legitimately needs beyond what appears statically:
#   basic latin (paths, code, digits), Bengali block + Vedic-adjacent
#   marks used by NCTB texts, and the math/typography symbols the
#   markdown renderer can emit.
EXTRA_RANGES = [
    range(0x0020, 0x007F),  # basic latin printable
    range(0x00A0, 0x0100),  # latin-1 supplement (x, /, degree, ...)
    range(0x0964, 0x0966),  # danda, double danda
    range(0x0970, 0x09FF),  # Oriya block end boundary -> keep Bengali fully
    range(0x0980, 0x09FE),  # Bengali block incl. digits 09E6-09EF
    range(0x2000, 0x2014),  # dashes, quotes, ellipsis
    range(0x2018, 0x2027),
    range(0x2212, 0x221F),  # minus, plus-minus, sqrt, prop, tilde operators
    range(0x2248, 0x2249),  # approx
]


def ui_charset() -> set[int]:
    chars: set[int] = set()
    for ext in ("*.ts", "*.tsx", "*.css"):
        for f in (WEB / "src").rglob(ext):
            chars.update(ord(c) for c in f.read_text(encoding="utf-8", errors="ignore"))
    for spec in EXTRA_RANGES:
        chars.update(spec)
    return chars


def subset_to_woff2(src: Path, charset: set[int]) -> bytes:
    font = TTFont(src)
    opts = Options()
    opts.flavor = "woff2"
    opts.drop_tables += ["DSIG"]
    opts.layout_features = [
        "kern", "liga", "calt", "mark", "mkmk", "akhn", "half", "pres", "blwf", "cjct",
    ]
    opts.name_IDs = [1, 2]
    opts.notdef_outline = True
    sub = Subsetter(options=opts)
    sub.populate(unicodes=charset)
    sub.subset(font)
    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    return buf.getvalue()


def main() -> int:
    charset = ui_charset()
    print(f"UI charset size: {len(charset)} codepoints")
    if not FULL_TTF.exists():
        print(f"missing source font: {FULL_TTF}")
        return 2
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "font_subsets"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    targets = [("FULL NotoSansBengali-Regular.ttf", FULL_TTF)]
    dist = WEB / "dist" / "assets"
    if dist.exists():
        targets += [
            (f"dist:{p.name.split('-C')[0] if '-C' in p.name else p.name}", p)
            for p in sorted(dist.glob("*.woff2"))
            if "hind-siliguri" in p.name or "noto-sans-bengali" in p.name
        ]
    for label, path in targets:
        before = path.stat().st_size
        data = subset_to_woff2(path, charset)
        out = out_dir / (path.stem + ".ui.woff2")
        out.write_bytes(data)
        rows.append((label, before, len(data)))

    print(f"{'font':58} {'before':>9} {'subset':>9} {'saved':>8}")
    tb = ts = 0
    for label, before, after in rows:
        tb += before
        ts += after
        pct = (1 - after / before) * 100 if before else 0.0
        print(f"{label:58} {before:9,} {after:9,} {pct:7.1f}%")
    print(f"{'TOTAL':58} {tb:9,} {ts:9,} {(1 - ts / tb) * 100:7.1f}%")
    print(f"subset files written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
