#!/usr/bin/env python
"""CLI over :mod:`bangla_gpt_api.providers.image_safety` (AUD-A2-17 / A6-09).

Run it from ``apps/api`` (the package is installed editable there):

    python scripts/image_sanitize.py photo.jpg               # report only
    python scripts/image_sanitize.py photo.jpg -o clean.jpg  # write the bytes
    python scripts/image_sanitize.py --exif photo.jpg        # dump metadata found

Exit codes: 0 sanitized, 2 refused (quality/decodable), 1 usage or IO error.
The tool never contacts a provider; it exists so an operator can check a
picture with the exact rules the app applies before it reaches a model.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from pathlib import Path

# scripts/ is not a package; make src/ importable when running from a checkout
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bangla_gpt_api.providers.image_safety import (  # noqa: E402 (path set above)
    ImageQualityError,
    ImageSanitizeError,
    sanitize_image,
)


def _declared_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def _exif_summary(raw: bytes) -> dict:
    """Read the metadata the sanitizer is about to remove (report only)."""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(raw)) as image:
            exif = dict(image.getexif())
    except Exception:  # noqa: BLE001 - a report helper, never a gate
        return {}
    summary: dict[str, object] = {}
    for tag, value in list(exif.items())[:20]:
        summary[str(tag)] = str(value)[:80]
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sanitize one image the way the chat path does.")
    parser.add_argument("path", type=Path, help="image file (png/jpeg/webp)")
    parser.add_argument("-o", "--output", type=Path, help="write sanitized bytes here")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument(
        "--exif", action="store_true", help="also dump metadata found (report only)"
    )
    args = parser.parse_args(argv)

    if not args.path.is_file():
        print(f"not a file: {args.path}", file=sys.stderr)
        return 1
    raw = args.path.read_bytes()
    mime = _declared_mime(args.path)
    if args.exif:
        detected = _exif_summary(raw)
        print(json.dumps({"exif_found": detected}, ensure_ascii=False, indent=2))
    try:
        sanitized = sanitize_image(raw, mime)
    except ImageQualityError as exc:
        print(f"REFUSED (quality): {exc}", file=sys.stderr)
        return 2
    except ImageSanitizeError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    report = {
        "input": str(args.path),
        "declared_mime": mime,
        "output_mime": sanitized.mime_type,
        "width": sanitized.width,
        "height": sanitized.height,
        "edge_std": round(sanitized.edge_std, 2),
        "bytes_in": sanitized.bytes_in,
        "bytes_out": sanitized.bytes_out,
    }
    if args.output:
        args.output.write_bytes(sanitized.data)
        report["written"] = str(args.output)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"ok: {sanitized.width}x{sanitized.height} edge_std={sanitized.edge_std:.2f} "
            f"{mime} -> {sanitized.mime_type} ({sanitized.bytes_in} -> {sanitized.bytes_out} bytes)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
