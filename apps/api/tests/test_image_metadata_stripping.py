"""The payload leaving the API carries no metadata (AUD-A2-17 / A6-09).

A phone photo of a homework page carries GPS, a capture timestamp, a device
serial and often a free-text comment. Every one of those used to be forwarded
verbatim to the third-party vision model: `_validate_chat_image` checked the
mime, the size and the magic bytes, then returned the student's bytes
unchanged. These tests pin the round trip that removes them, and the format
rule that decides what the re-encoded bytes are.

Fixtures are generated here with Pillow rather than committed as binaries: the
metadata being tested is what the fixture carries, so it has to be visible in
the test that plants it.
"""

import base64
import io

import pytest
from PIL import Image, PngImagePlugin, TiffImagePlugin

from bangla_gpt_api.providers import image_safety
from bangla_gpt_api.providers.image_safety import (
    ImageSanitizeError,
    ImageSupportUnavailable,
    sanitize_image,
    sanitize_inline_image,
)
from bangla_gpt_api.routers.common import _validate_chat_image
from bangla_gpt_api.schemas import ChatImageIn

CAMERA = "BGPT-TESTCAMERA"
COMMENT = "BGPT-TESTCOMMENT"
#: EXIF tag id of the GPS sub-IFD (where the location actually lives).
GPS_IFD = 0x8825


def _jpeg_with_exif(size: tuple[int, int] = (64, 64)) -> bytes:
    img = Image.new("RGB", size, (200, 180, 120))
    exif = Image.Exif()
    exif[0x010F] = CAMERA  # Make
    exif[0x0131] = COMMENT  # Software
    gps = exif.get_ifd(GPS_IFD)  # where the location lives
    gps[1] = "N"
    gps[2] = tuple(TiffImagePlugin.IFDRational(v, 1) for v in (23, 48, 0))
    gps[3] = "E"
    gps[4] = tuple(TiffImagePlugin.IFDRational(v, 1) for v in (90, 24, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _png_with_text(size: tuple[int, int] = (64, 64), alpha: bool = False) -> bytes:
    img = Image.new("RGBA" if alpha else "RGB", size, (30, 90, 160, 255))
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("Comment", COMMENT)
    exif = Image.Exif()
    exif[0x010F] = CAMERA
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=pnginfo, exif=exif)
    return buf.getvalue()


def _webp_with_exif(size: tuple[int, int] = (64, 64)) -> bytes:
    img = Image.new("RGB", size, (12, 200, 90))
    exif = Image.Exif()
    exif[0x010F] = CAMERA
    buf = io.BytesIO()
    img.save(buf, format="WEBP", exif=exif)
    return buf.getvalue()


# --- the privacy contract -----------------------------------------------------


def test_jpeg_gps_and_camera_metadata_do_not_survive() -> None:
    raw = _jpeg_with_exif()
    # the fixture really carries what we are about to strip
    assert CAMERA.encode() in raw
    with Image.open(io.BytesIO(raw)) as dirty:
        assert dict(dirty.getexif())
        assert dirty.getexif().get_ifd(GPS_IFD)  # GPS latitude/longitude

    out = sanitize_image(raw, "image/jpeg")

    assert out.mime_type == "image/jpeg"
    assert out.data != raw
    assert CAMERA.encode() not in out.data
    assert COMMENT.encode() not in out.data
    with Image.open(io.BytesIO(out.data)) as clean:
        assert not dict(clean.getexif())
        assert not clean.getexif().get_ifd(GPS_IFD)
        assert "exif" not in clean.info
    assert out.bytes_in == len(raw) and out.bytes_out == len(out.data)


def test_png_text_and_exif_chunks_do_not_survive() -> None:
    raw = _png_with_text(alpha=True)  # alpha keeps the PNG format (below)
    assert COMMENT.encode() in raw

    out = sanitize_image(raw, "image/png")

    assert COMMENT.encode() not in out.data
    assert CAMERA.encode() not in out.data
    with Image.open(io.BytesIO(out.data)) as clean:
        assert "Comment" not in clean.info
        assert "exif" not in clean.info


def test_webp_exif_does_not_survive() -> None:
    raw = _webp_with_exif()
    assert CAMERA.encode() in raw

    out = sanitize_image(raw, "image/webp")

    assert CAMERA.encode() not in out.data
    with Image.open(io.BytesIO(out.data)) as clean:
        assert not dict(clean.getexif())


def test_inline_payload_shape_is_base64_in_base64_out() -> None:
    raw = _jpeg_with_exif()
    out = sanitize_inline_image("image/jpeg", base64.b64encode(raw).decode())
    assert base64.b64decode(out.base64()) == out.data
    assert CAMERA.encode() not in out.data


def test_route_validator_returns_sanitized_bytes() -> None:
    """The one boundary that turns outside bytes into a provider payload."""
    raw = _jpeg_with_exif()
    payload = _validate_chat_image(
        ChatImageIn(mime_type="image/jpeg", data_base64=base64.b64encode(raw).decode())
    )
    assert payload is not None
    assert "gps" not in payload["data"].lower()
    forwarded = base64.b64decode(payload["data"])
    assert CAMERA.encode() not in forwarded
    assert payload["mime_type"] == "image/jpeg"


# --- what the re-encode guarantees about the format ---------------------------


def test_opaque_image_is_re_encoded_as_jpeg_even_when_sent_as_png() -> None:
    """PNG is kept only for transparency: JPEG is far smaller for a photo."""
    out = sanitize_image(_png_with_text(alpha=False), "image/png")
    assert out.mime_type == "image/jpeg"


def test_transparent_png_keeps_png() -> None:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = sanitize_image(buf.getvalue(), "image/png")
    assert out.mime_type == "image/png"
    with Image.open(io.BytesIO(out.data)) as clean:
        assert clean.mode == "RGBA"


def test_fully_opaque_alpha_channel_is_not_a_reason_for_png() -> None:
    out = sanitize_image(_png_with_text(alpha=True, size=(16, 16)), "image/png")
    assert out.mime_type == "image/jpeg"


def test_returned_mime_matches_the_bytes() -> None:
    for raw, mime in (
        (_jpeg_with_exif(), "image/jpeg"),
        (_png_with_text(alpha=True), "image/png"),
        (_webp_with_exif(), "image/webp"),
    ):
        out = sanitize_image(raw, mime)
        with Image.open(io.BytesIO(out.data)) as clean:
            assert clean.format == ("JPEG" if out.mime_type == "image/jpeg" else "PNG")


# --- refusals -----------------------------------------------------------------


def test_truncated_image_is_refused_not_forwarded() -> None:
    raw = _jpeg_with_exif()
    with pytest.raises(ImageSanitizeError):
        sanitize_image(raw[: len(raw) // 3], "image/jpeg")


def test_decompression_bomb_is_refused_by_pixel_count(monkeypatch) -> None:
    monkeypatch.setattr(image_safety, "MAX_PIXELS", 100)
    with pytest.raises(ImageSanitizeError) as exc:
        sanitize_image(_jpeg_with_exif(size=(64, 64)), "image/jpeg")
    assert "too large" in str(exc.value)


def test_unsupported_and_empty_payloads_are_refused() -> None:
    with pytest.raises(ImageSanitizeError):
        sanitize_image(b"\x00\x01", "image/tiff")
    with pytest.raises(ImageSanitizeError):
        sanitize_image(b"", "image/png")
    with pytest.raises(ImageSanitizeError):
        sanitize_inline_image("image/png", "not base64!!")


def test_missing_pillow_is_a_deployment_fault_not_a_bad_request(monkeypatch) -> None:
    """503, not 422: an unavailable sanitizer must not blame the photo."""
    import builtins

    real_import = builtins.__import__

    def _no_pillow(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no PIL")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pillow)
    with pytest.raises(ImageSupportUnavailable):
        sanitize_image(_jpeg_with_exif(), "image/jpeg")
