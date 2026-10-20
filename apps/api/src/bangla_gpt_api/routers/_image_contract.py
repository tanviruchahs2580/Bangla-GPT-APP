"""Chat image (vision) contract: decode, sniff and scan an inline image.

Extracted from ``routers/common.py`` for cohesion and file size (C-03): the
whole "what bytes may reach a vision provider" policy lives here — the
allowed-mime set, the decoded-size ceiling, magic-byte sniffing (S-011), the
malware-scan seam (A2-09) and the 422 envelope every failure uses. The helpers
are re-exported from ``routers.common``, which stays the import path for the
routes and the tests.
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import HTTPException

from bangla_gpt_api.schemas import ChatImageIn
from bangla_gpt_api.services.malware_scan import scan_inline_image

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
    content that does not match the declared type, a malware-scan flag -- is a
    422 with a stable detail code (never a partial accept). ``image_invalid``
    covers the existing envelope failures; ``image_type_mismatch`` covers bytes
    whose magic number does not match the declared (allowed) mime type;
    ``image_malware_detected`` covers a scanner verdict (services.malware_scan,
    A2-09: the default scanner is the documented no-op unless one is wired).
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
    # A2-09: malware-scan seam. The default scanner is the documented no-op
    # (see services/malware_scan.py); a deployment wires a real engine behind
    # the same protocol, and a flag is refused here with its own detail code
    # before the bytes can reach a provider or an OCR run.
    scan = scan_inline_image(raw)
    if scan.flagged:
        raise HTTPException(status_code=422, detail=scan.to_error_detail())
    # The decode above is validation only. Providers embed this dict in JSON
    # payloads (Gemini inline_data), so it must carry the base64 STRING —
    # raw bytes would raise TypeError at request-encoding time.
    return {"mime_type": mime, "data": base64.b64encode(raw).decode("ascii")}
