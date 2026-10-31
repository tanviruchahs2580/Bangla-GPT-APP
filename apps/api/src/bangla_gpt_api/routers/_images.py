"""Inline chat-image validation and metadata stripping (split from common.py, F-077).

One concern: every byte of client image data is sniffed, size-bounded and
re-encoded here before any provider payload can name it. ``routers/common.py``
re-exports these names for the import sites that predate the split.
"""

import base64
import logging
from typing import Any

from fastapi import HTTPException

from bangla_gpt_api.schemas import ChatImageIn

logger = logging.getLogger(__name__)

#: Mime types the vision contract accepts (declared AND sniff-verified).
_IMAGE_MIME_ALLOWED = frozenset({"image/png", "image/jpeg", "image/webp"})

# Decoded size ceiling (base64 inflates ~4/3, so ~2 MB of JSON on the wire).
_IMAGE_MAX_BYTES = 1_500_000


def _sniff_image_mime(raw: bytes) -> str | None:
    """Magic-byte sniffing for the three allowed formats (stdlib only).

    The declared ``mime_type`` is client input; without this check any bytes
    could be forwarded to the third-party vision model labelled ``image/png``
    (S-011). Returns the sniffed MIME or None when no allowed signature
    matches, so the caller rejects instead of guessing.
    """
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    # RIFF container: "RIFF" <4-byte size> "WEBP"
    if len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validate_chat_image(image: ChatImageIn | None) -> dict[str, Any] | None:
    """Decode + validate an inline image, returning the provider payload dict
    ``{"mime_type":..., "data": <base64 string>}`` or None for text-only turns.

    Every failure -- disallowed mime, undecodable base64, oversize payload,
    content that does not match the declared type -- is a 422 with a stable
    detail code (never a partial accept). ``image_invalid`` covers the
    existing envelope failures; ``image_type_mismatch`` covers bytes whose
    magic number does not match the declared (allowed) mime type.
    """
    if image is None:
        return None
    mime = image.mime_type.strip().lower()
    if mime not in _IMAGE_MIME_ALLOWED:
        raise HTTPException(
            status_code=422,
            detail={"code": "image_invalid", "message": "Unsupported image mime type"},
        )
    try:
        raw = base64.b64decode(image.data_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "image_invalid", "message": "Image data is not valid base64"},
        ) from exc
    if not raw or len(raw) > _IMAGE_MAX_BYTES:
        raise HTTPException(
            status_code=422,
            detail={"code": "image_invalid", "message": "Image is empty or exceeds size limit"},
        )
    # S-011: inspect the actual bytes. A text blob labelled image/png used to
    # be forwarded unchanged to the vision model; the declared type must match
    # the sniffed magic bytes.
    sniffed = _sniff_image_mime(raw)
    if sniffed is None or sniffed != mime:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "image_type_mismatch",
                "message": "Image content does not match the declared mime type",
            },
        )
    # The decode above is validation only. Providers embed this dict in JSON
    # payloads (Gemini inline_data), so it must carry the base64 STRING —
    # raw bytes would raise TypeError at request-encoding time.
    #
    # The bytes themselves are NOT forwarded as sent. A phone photo of a
    # homework page carries GPS, a capture timestamp and often a device
    # serial; every one of those left the API toward a third-party vision
    # model. The image is re-encoded without metadata here — at the one
    # boundary that turns outside bytes into a provider payload — so no
    # caller has to remember to do it.
    return _sanitized_image_payload(mime, raw)


def _sanitized_image_payload(mime: str, raw: bytes) -> dict[str, Any]:
    """Re-encode a validated image without metadata, or answer honestly.

    Kept separate from `_validate_chat_image` so a sanitizer failure has its
    own code path: unreadable/unsupported content is the caller's fault (422
    ``image_invalid``), a missing Pillow is the deployment's (503
    ``image_support_unavailable``).
    """
    from bangla_gpt_api.providers.image_safety import (
        ImageSanitizeError,
        ImageSupportUnavailable,
        sanitize_image,
    )

    try:
        sanitized = sanitize_image(raw, mime)
    except ImageSupportUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "image_support_unavailable",
                "message": "Image processing is unavailable on the server",
            },
        ) from exc
    except ImageSanitizeError as exc:
        # The class name stays in the log line the sanitizer already writes;
        # the API message is for the client, not for a stack trace.
        logger.info("chat image rejected: %s", exc)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "image_invalid",
                "message": "Image could not be decoded or re-encoded",
            },
        ) from exc
    return {"mime_type": sanitized.mime_type, "data": sanitized.base64()}
