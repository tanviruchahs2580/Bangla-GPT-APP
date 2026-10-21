"""Untrusted image handling at the provider boundary (AUD-A2-17 / A6-09).

The chat route already validates an inline image (mime allowlist, base64
decode, decoded-size cap, magic-byte sniff). What it did NOT do is strip
metadata or look at whether the picture is usable at all. This module is the
second, independent pass that runs immediately before the bytes reach a
provider payload:

* full decode (a truncated or hostile file fails here, not upstream),
* bounded dimensions (decompression bomb guard),
* quality gate: images too small, too flat or too blurry are refused with an
  honest "please send a clearer photo" message instead of being sent to a
  vision model that would guess,
* re-encode into a metadata-free image: EXIF (GPS, camera serial, timestamps,
  user comments), PNG text chunks, WebP EXIF/XMP and any trailing bytes after
  the image payload do not survive the round trip,
* animated inputs are reduced to their first frame.

Pillow is imported lazily: the sanitizer reports a clear error when the image
support is not installed instead of failing at import time.
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Minimum side length. Below this a Bangla textbook photo is unreadable and a
#: vision model answers from imagination instead of the picture.
MIN_SIDE_PX = 32
#: Refuse anything larger than this many pixels before converting it (Pillow's
#: own DecompressionBombWarning triggers around 89M pixels; a real photo that
#: a student sends is far below this).
MAX_PIXELS = 24_000_000
#: Edge-energy floor for "not blank / not hopelessly blurry": the standard
#: deviation of the edge map, measured AFTER cropping the filter's border
#: response (Pillow's FIND_EDGES treats out-of-image pixels as 0, so the frame
#: itself reads as a hard edge and would swamp the statistic).
#: Measured on generated fixtures (2026-10-19, Pillow 12.3; two runs, evidence
#: E-R2-rag2-023): blank page 0.00, Gaussian-blurred text page sigma=4 -> 2.3,
#: sigma=8 -> 1.2-1.4, readable blur sigma=2 -> 10.6-11.0, sharp synthetic
#: text page -> 57-73, small two-tone photo -> 46.4. 6.0 separates the
#: unreadable cluster from the readable one.
MIN_EDGE_STD = 6.0
#: Border strip removed from the edge map before measuring (see MIN_EDGE_STD).
_EDGE_BORDER_PX = 2
#: JPEG quality used when re-encoding a JPEG (visually lossless for
#: photographs; the point of the re-encode is metadata removal).
JPEG_QUALITY = 92
JPEG_MIMES = frozenset({"image/jpeg"})
SUPPORTED_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})


class ImageSanitizeError(RuntimeError):
    """The image could not be turned into a safe, usable payload."""


class ImageQualityError(ImageSanitizeError):
    """The image decoded but is too small/flat to be honestly readable."""


@dataclass(frozen=True)
class SanitizedImage:
    """Metadata-free image bytes plus the format they are now in."""

    data: bytes
    mime_type: str
    width: int
    height: int
    bytes_in: int
    bytes_out: int
    edge_std: float

    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


def sanitize_image(raw: bytes, declared_mime: str) -> SanitizedImage:
    """Decode, quality-check and re-encode one untrusted image.

    Raises :class:`ImageQualityError` for unusable pictures and
    :class:`ImageSanitizeError` for anything that is not a decodable image of
    an allowed type. The returned bytes carry no metadata and the returned
    mime type is what the bytes actually are.
    """
    mime = (declared_mime or "").strip().lower()
    if mime not in SUPPORTED_MIMES:
        raise ImageSanitizeError(f"unsupported image type: {mime or 'missing'}")
    if not raw:
        raise ImageSanitizeError("empty image payload")
    try:
        from PIL import Image, ImageFilter, ImageStat
    except ImportError as exc:  # pragma: no cover - exercised by the error test
        raise ImageSanitizeError("image sanitizer unavailable: Pillow is not installed") from exc

    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.load()  # full decode; truncated/hostile files fail here
            width, height = source.size
            if width < MIN_SIDE_PX or height < MIN_SIDE_PX:
                raise ImageQualityError(
                    f"image too small to read ({width}x{height} < {MIN_SIDE_PX}px)"
                )
            if width * height > MAX_PIXELS:
                raise ImageSanitizeError(f"image too large to sanitize ({width * height} px)")
            # Blur/blankness: standard deviation of the edge map, border
            # excluded (see MIN_EDGE_STD for the calibration).
            grey = source.convert("L")
            edges = grey.filter(ImageFilter.FIND_EDGES).crop(
                (
                    _EDGE_BORDER_PX,
                    _EDGE_BORDER_PX,
                    max(_EDGE_BORDER_PX + 1, width - _EDGE_BORDER_PX),
                    max(_EDGE_BORDER_PX + 1, height - _EDGE_BORDER_PX),
                )
            )
            stddev = ImageStat.Stat(edges).stddev
            edge = float(stddev[0]) if stddev else 0.0
            if edge < MIN_EDGE_STD:
                raise ImageQualityError(f"image looks blank or too blurry (edge_std={edge:.2f})")
            mode = "RGB" if mime in JPEG_MIMES else "RGBA"
            converted = source.convert(mode)
    except ImageQualityError:
        raise
    except ImageSanitizeError:
        raise
    except Exception as exc:  # Pillow raises several unrelated error types here
        raise ImageSanitizeError(f"image could not be decoded: {type(exc).__name__}") from exc

    # A fresh image object with an empty info dict: nothing carries over into
    # the encoder (Pillow writes EXIF/ICC/pnginfo only when told to, and this
    # guarantees the source metadata is not even available to it).
    clean = converted.copy()
    clean.info = {}
    buffer = io.BytesIO()
    if mime in JPEG_MIMES:
        clean.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=False)
        out_mime = "image/jpeg"
    else:
        # WebP is re-encoded as PNG: a lossless metadata-free container that
        # every vision provider accepts.
        clean.save(buffer, format="PNG", optimize=False)
        out_mime = "image/png"
    data = buffer.getvalue()
    logger.info(
        "image_sanitized: %s -> %s %dx%d edge_std=%.2f bytes %d->%d",
        mime,
        out_mime,
        width,
        height,
        edge,
        len(raw),
        len(data),
    )
    return SanitizedImage(
        data=data,
        mime_type=out_mime,
        width=width,
        height=height,
        bytes_in=len(raw),
        bytes_out=len(data),
        edge_std=edge,
    )


def sanitize_inline_image(mime_type: str, data_base64: str) -> SanitizedImage:
    """Sanitize the chat route's inline payload shape.

    Input is the route-validated ``{"mime_type", "data"}`` pair (``data`` is
    base64); output is a metadata-free image in the same wire shape via
    :meth:`SanitizedImage.base64`.
    """
    try:
        raw = base64.b64decode(data_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ImageSanitizeError("image data is not valid base64") from exc
    return sanitize_image(raw, mime_type)
