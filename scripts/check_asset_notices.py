"""Bundled-image notice guard (REPO-07 / F-137).

Every image the web app ships must be named in ``THIRD_PARTY_NOTICES.md``.
The current nine entries sit in the "Bundled images (licence record owed)"
section because their provenance was never recorded; the owner records the
real licence there or replaces the file. What this check prevents is a *new*
image arriving with no notices entry at all.

    python scripts/check_asset_notices.py   # exit 1 lists the unnamed files
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg"}


def shipped_images() -> list[Path]:
    assets = ROOT / "apps" / "web" / "src" / "assets"
    icons = ROOT / "apps" / "web" / "public"
    images = [p for p in assets.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES]
    images += [p for p in icons.glob("icon-*") if p.suffix.lower() in IMAGE_SUFFIXES]
    return sorted(images)


def main() -> int:
    notices = NOTICES.read_text(encoding="utf-8")
    unnamed = [
        p.relative_to(ROOT).as_posix()
        for p in shipped_images()
        if p.relative_to(ROOT).as_posix() not in notices
    ]
    if unnamed:
        print(
            f"FAIL: {len(unnamed)} bundled image(s) are not named in THIRD_PARTY_NOTICES.md:"
        )
        for name in unnamed:
            print(f"  {name}")
        return 1
    print(
        f"OK: all {len(shipped_images())} bundled images are named in THIRD_PARTY_NOTICES.md"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
