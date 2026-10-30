"""Untrusted image handling at the provider boundary (AUD-A2-17 / A6-09).

The chat route validates an inline image before this runs (mime allowlist,
base64 decode, decoded-size cap, magic-byte sniff). What the route did NOT
do is remove the metadata the file carries, and a phone photo of a homework
page is metadata-rich: GPS coordinates of the child's home, the capture
timestamp, the camera serial, sometimes a device model and free-text comment.
None of that is needed to answer a question about a textbook, and all of it
was being forwarded verbatim to a third-party vision model
(`providers/gemini.py` embeds the bytes as ``inline_data``).

This module re-encodes every accepted image through a full decode, so the
payload that leaves the API is pixel-equivalent and metadata-free:

* EXIF (including the GPS sub-IFD), XMP, ICC profiles, PNG text chunks and
  any trailing bytes after the image payload do not survive the round trip;
* a truncated or hostile file fails here with a 422 instead of upstream;
* a decompression bomb is refused by pixel count before it is converted;
* an animated input is reduced to its first frame.

Pillow is imported lazily so the API still boots without it; the chat route
then answers 503 ``image_support_unavailable`` rather than blaming the
student's photo for a deployment fault.

Deliberately NOT here: a "too small / too blurry to read" quality gate exists
on the enterprise-audit branch (`chore/enterprise-hardening-20261018`,
``providers/image_safety.py``) with thresholds measured on *generated*
fixtures. Refusing real photos needs thresholds validated against real
student submissions, so it stays a separate, deliberate product decision
rather than shipping a guess.
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Everything the route may hand us (routers/common.py:_IMAGE_MIME_ALLOWED).
SUPPORTED_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
#: Pixel ceiling applied before conversion. Pillow's own decompression-bomb
#: warning fires around 89M pixels; a textbook photo is far below this, and a
#: 24M-pixel ceiling still lets a 6000x4000 camera image through.
MAX_PIXELS = 24_000_000
#: JPEG quality for the metadata-free re-encode. Visually lossless for
#: photographs; the point of the re-encode is metadata removal, not shrinking.
JPEG_QUALITY = 92


class ImageSanitizeError(RuntimeError):
    """The payload is not a usable image (the caller answers 422)."""


class ImageSupportUnavailable(RuntimeError):
    """Pillow is not installed: a deployment fault, not a bad request (503)."""


@dataclass(frozen=True)
class SanitizedImage:
    """Metadata-free image bytes plus the format they are now in."""

    data: bytes
    mime_type: str
    width: int
    height: int
    bytes_in: int
    bytes_out: int

    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


def _output_format(source: object, mime: str) -> str:
    """JPEG unless the image actually carries transparency.

    PNG is the safe answer for alpha (JPEG cannot represent it) and the
    expensive one for everything else: a WebP photo of a page re-encoded as
    PNG is two to three times the size of the same pixels as JPEG, on a
    payload that is about to be inlined in a provider request. So the rule is
    the format's own constraint, not a size heuristic: transparency decides.
    """
    if mime == "image/jpeg":
        return "JPEG"
    try:
        # Pillow ships no stubs in this dependency set, so the attribute set is
        # untyped here; the except below is the documented fallback.
        alpha = source.getbands()[-1] == "A"  # type: ignore[attr-defined] - Pillow untyped
        if not alpha:
            return "JPEG"
        # A fully opaque alpha channel is still no reason to send PNG.
        extrema = source.getchannel("A").getextrema()  # type: ignore[attr-defined] - Pillow untyped
        return "PNG" if extrema[0] < 255 else "JPEG"
    except (AttributeError, ValueError, OSError):
        return "PNG"


def sanitize_image(raw: bytes, declared_mime: str) -> SanitizedImage:
    """Decode and re-encode one untrusted image without its metadata.

    Raises :class:`ImageSupportUnavailable` when Pillow is missing and
    :class:`ImageSanitizeError` for anything that is not a decodable image of
    an allowed type. The returned ``mime_type`` is what the bytes actually
    are, never what the client claimed.
    """
    mime = (declared_mime or "").strip().lower()
    if mime not in SUPPORTED_MIMES:
        raise ImageSanitizeError(f"unsupported image type: {mime or 'missing'}")
    if not raw:
        raise ImageSanitizeError("empty image payload")

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - exercised by the error test
        raise ImageSupportUnavailable(
            "image sanitizer unavailable: Pillow is not installed"
        ) from exc

    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.load()  # full decode: truncated or hostile files fail here
            width, height = source.size
            if width <= 0 or height <= 0:
                raise ImageSanitizeError("image has no pixels")
            if width * height > MAX_PIXELS:
                raise ImageSanitizeError(f"image too large to sanitize ({width * height} px)")
            out_format = _output_format(source, mime)
            # A fresh object with an empty info dict: nothing carries over
            # into the encoder (Pillow writes EXIF/ICC/pnginfo only when told
            # to, and this guarantees the source metadata is not even
            # reachable from the object being saved).
            clean = source.convert("RGB" if out_format == "JPEG" else "RGBA")
    except ImageSanitizeError:
        raise
    except Exception as exc:  # Pillow raises unrelated error types for bad bytes
        raise ImageSanitizeError(f"image could not be decoded: {type(exc).__name__}") from exc

    clean.info = {}
    buffer = io.BytesIO()
    try:
        if out_format == "JPEG":
            clean.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=False)
            out_mime = "image/jpeg"
        else:
            clean.save(buffer, format="PNG", optimize=False)
            out_mime = "image/png"
    except Exception as exc:  # encoding failure is still a bad-image answer
        raise ImageSanitizeError(f"image could not be re-encoded: {type(exc).__name__}") from exc

    data = buffer.getvalue()
    logger.info(
        "image_sanitized mime=%s->%s size=%dx%d bytes=%d->%d",
        mime,
        out_mime,
        width,
        height,
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
    )


def sanitize_inline_image(mime_type: str, data_base64: str) -> SanitizedImage:
    """Sanitize the chat route's inline payload shape.

    Input is the route-validated ``{"mime_type", "data"}`` pair (``data`` is
    base64); the output carries the same wire shape via
    :meth:`SanitizedImage.base64`.
    """
    try:
        raw = base64.b64decode(data_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ImageSanitizeError("image data is not valid base64") from exc
    return sanitize_image(raw, mime_type)
