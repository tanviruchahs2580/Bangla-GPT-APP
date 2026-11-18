"""Measure the shipped webfonts and derive metric-matched fallback descriptors.

E5 Phase 2 requires the fallback @font-face descriptors (size-adjust,
ascent-override, descent-override, line-gap-override) to be MEASURED, not
guessed. This script reads the actual SFNT metrics of the shipped WOFF2 and
of the platform fallback font, then derives the descriptors with the
fontaine/nextjs formula:

    s = target_avg_width / fallback_avg_width          -> size-adjust: s*100%
    ascent-override%  = (target_ascent  / target_upm) / s * 100
    descent-override% = (target_descent / target_upm) / s * 100
    line-gap-override% = (target_linegap / target_upm) / s * 100

With size-adjust s the fallback's em is scaled by s, so its (overridden)
vertical metrics must be divided by s to land at the target's absolute
ratios. When the fallback IS the target family (Android's system Noto Sans
Bengali), s = 100% and the overrides equal the font's own natural metrics —
pinning version drift instead of distorting anything.

Usage (from apps/web):
    python scripts/font_metrics.py [--fallback C:\\Windows\\Fonts\\Nirmala.ttf]

Requires fontTools + brotli (dev-only tools; not runtime dependencies).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

# Representative Bengali charset for the average-advance measurement — the
# same set is measured in every font so the ratio is apples-to-apples.
# Combining marks (vowel signs, virama, nukta) are included: they are part
# of real Bengali line layout even though several carry near-zero advances.
CHARSET = (
    "অআইঈউঊঋএঐওঔকখগঘঙচছজঝঞটঠডঢণতথদধনপফবভমযরলশষসহ"
    "ািীুূৃেৈোৌ্ঁংঃ০১২৩৪৫৬৭৮৯"
)


def font_metrics(path: Path, font_number: int = 0) -> dict:
    font = TTFont(str(path), fontNumber=font_number)
    return _metrics_from_font(font, path)


def _metrics_from_font(font, path: Path) -> dict:
    upm = font["head"].unitsPerEm
    hhea = font["hhea"]
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    advances = []
    skipped = []
    for ch in CHARSET:
        codepoint = ord(ch)
        if codepoint not in cmap:
            skipped.append(ch)
            continue
        advances.append(hmtx[cmap[codepoint]][0])
    if not advances:
        raise SystemExit(f"no charset glyphs found in {path}")
    name = font["name"].getDebugName(4) or path.name
    return {
        "name": name,
        "upm": upm,
        "ascent": hhea.ascent,
        "descent": hhea.descent,  # negative in SFNT
        "lineGap": hhea.lineGap,
        "avg": sum(advances) / len(advances),
        "n_glyphs": len(advances),
        "skipped": "".join(skipped),
    }


def main() -> int:
    here = Path(__file__).resolve().parent
    target_path = here.parent / "public" / "fonts" / "noto-sans-bengali-bengali-400-normal.woff2"
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fallback",
        default=r"C:\Windows\Fonts\Nirmala.ttc",
        help="platform fallback font (Windows Bengali UI font; .ttc supported)",
    )
    parser.add_argument(
        "--fallback-face",
        default="Nirmala UI",
        help="which face inside a .ttc collection to measure (full name)",
    )
    args = parser.parse_args()

    target = font_metrics(target_path)
    print(f"TARGET  {target_path.name}")
    for k, v in target.items():
        print(f"  {k}: {v}")

    fallback_path = Path(args.fallback)
    if not fallback_path.exists():
        print(f"\nFALLBACK {fallback_path} not found — descriptors not derived.")
        return 1
    if fallback_path.suffix.lower() == ".ttc":
        # A collection holds several faces; measure the requested style.
        fb = None
        for i in range(sys.maxsize):
            try:
                cand = font_metrics(fallback_path, i)
            except Exception:
                break
            print(f"  [ttc face {i}] {cand['name']}")
            if cand["name"] == args.fallback_face:
                fb = cand
                break
        if fb is None:
            print(f"face '{args.fallback_face}' not found in collection")
            return 1
    else:
        fb = font_metrics(fallback_path)
    print(f"\nFALLBACK {fallback_path.name}")
    for k, v in fb.items():
        print(f"  {k}: {v}")

    # Average advances are only comparable after em-normalisation: the two
    # fonts may use different unitsPerEm (Noto 1000, Nirmala UI 2048).
    s = (target["avg"] / target["upm"]) / (fb["avg"] / fb["upm"])
    size_adjust = s * 100
    ascent = (target["ascent"] / target["upm"]) / s * 100
    descent = (-target["descent"] / target["upm"]) / s * 100  # report positive
    line_gap = (target["lineGap"] / target["upm"]) / s * 100

    print("\nDESCRIPTORS (fontaine formula, 2-decimal rounding)")
    print(f"  size-adjust: {size_adjust:.2f}%")
    print(f"  ascent-override: {ascent:.2f}%")
    print(f"  descent-override: {descent:.2f}%")
    print(f"  line-gap-override: {line_gap:.2f}%")

    # The Android face (local Noto Sans Bengali) is pinned to the target's
    # own natural ratios with size-adjust 100%.
    print("\nANDROID PIN (local Noto Sans Bengali, size-adjust 100%)")
    print(f"  ascent-override: {target['ascent'] / target['upm'] * 100:.2f}%")
    print(f"  descent-override: {-target['descent'] / target['upm'] * 100:.2f}%")
    print(f"  line-gap-override: {target['lineGap'] / target['upm'] * 100:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
