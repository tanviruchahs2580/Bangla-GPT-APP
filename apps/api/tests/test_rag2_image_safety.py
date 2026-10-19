"""AUD-A2-17 / A6-09: the image path strips metadata and refuses junk.

Pinned here:

* a JPEG with EXIF (GPS, user comment, camera model) comes out of the
  sanitizer re-encoded with none of it -- asserted by scanning the output
  bytes for the injected markers, not by trusting a flag;
* a PNG text chunk and bytes appended after the image payload (a polyglot)
  do not survive either; WebP is re-encoded as metadata-free PNG; an animated
  input is reduced to its first frame;
* blank, hopelessly blurry and tiny images are refused ("image_unreadable")
  instead of being sent to a vision model that would guess, and the provider
  is never called for them;
* the tutor's ask/ask_stream paths run this second pass, so a hostile or
  unreadable payload cannot reach a provider through them.
"""

from __future__ import annotations

import base64
import io
from typing import ClassVar

import pytest
from PIL import Image, ImageDraw, ImageFilter

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.providers.image_safety import (
    MIN_EDGE_STD,
    ImageQualityError,
    ImageSanitizeError,
    sanitize_image,
    sanitize_inline_image,
)
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.services.tutor import IMAGE_UNREADABLE_ANSWER, TutorService

GPS_MARKER = b"rag2-gps-marker"
COMMENT_MARKER = b"rag2-user-comment-marker"
PNG_TEXT_MARKER = b"rag2-png-text-marker"
TRAILING_MARKER = b"rag2-trailing-payload-marker"

CHUNK_TEXT = "কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক। কোষেই সকল জৈবনিক কাজ ঘটে।"


def _page(size: tuple[int, int] = (400, 300)) -> Image.Image:
    """A sharp synthetic 'textbook page' that must pass the quality gate."""
    page = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(page)
    for line in range(8):
        y = 30 + line * 30
        draw.line([(30, y), (size[0] - 30, y)], fill=(0, 0, 0), width=3)
        draw.line([(30, y + 6), (size[0] - 120, y + 6)], fill=(0, 0, 0), width=2)
    return page


def _hostile_jpeg() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "rag2-camera"  # Make
    exif[0x8825] = {1: "N", 2: (23.0, 46.0, 0.0)}  # GPSInfo
    exif[0x9286] = COMMENT_MARKER.decode()  # UserComment
    buffer = io.BytesIO()
    _page().save(buffer, format="JPEG", quality=95, exif=exif)
    return buffer.getvalue()


def _png_with_text_chunk() -> bytes:
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", PNG_TEXT_MARKER.decode())
    buffer = io.BytesIO()
    _page().save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def _blurry() -> bytes:
    buffer = io.BytesIO()
    _page().filter(ImageFilter.GaussianBlur(8)).save(buffer, format="PNG")
    return buffer.getvalue()


def _blank() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _tiny() -> bytes:
    buffer = io.BytesIO()
    _page((16, 16)).save(buffer, format="PNG")
    return buffer.getvalue()


# ------------------------------------------------------------- metadata -----
def test_jpeg_exif_is_stripped_by_re_encoding() -> None:
    raw = _hostile_jpeg()
    # sanity: the hostile markers are really in the input
    assert GPS_MARKER not in raw  # GPS is binary, the text markers are the probes
    assert COMMENT_MARKER in raw
    out = sanitize_image(raw, "image/jpeg")
    assert out.mime_type == "image/jpeg"
    assert COMMENT_MARKER not in out.data
    assert b"rag2-camera" not in out.data
    with Image.open(io.BytesIO(out.data)) as image:
        assert dict(image.getexif()) == {}
        assert image.size == (400, 300)
        assert image.format == "JPEG"


def test_png_text_chunks_are_stripped() -> None:
    raw = _png_with_text_chunk()
    assert PNG_TEXT_MARKER in raw
    out = sanitize_image(raw, "image/png")
    assert PNG_TEXT_MARKER not in out.data
    with Image.open(io.BytesIO(out.data)) as image:
        assert image.info.get("Comment") is None


def test_trailing_bytes_after_the_payload_are_dropped() -> None:
    buffer = io.BytesIO()
    _page().save(buffer, format="PNG")
    polyglot = buffer.getvalue() + TRAILING_MARKER + b"<script>alert(1)</script>"
    out = sanitize_image(polyglot, "image/png")
    assert TRAILING_MARKER not in out.data
    assert b"<script>" not in out.data


def test_webp_is_re_encoded_as_metadata_free_png() -> None:
    buffer = io.BytesIO()
    _page().save(buffer, format="WEBP")
    out = sanitize_image(buffer.getvalue(), "image/webp")
    assert out.mime_type == "image/png"
    assert out.data.startswith(b"\x89PNG\r\n\x1a\n")


def test_animated_input_is_reduced_to_one_frame() -> None:
    frames = [_page(), _page(), _page()]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="PNG", save_all=True, append_images=frames[1:], duration=100)
    raw = buffer.getvalue()
    out = sanitize_image(raw, "image/png")
    with Image.open(io.BytesIO(out.data)) as image:
        assert getattr(image, "n_frames", 1) == 1


# ---------------------------------------------------------------- quality ---
def test_blank_image_is_refused_with_a_quality_error() -> None:
    with pytest.raises(ImageQualityError, match="blank or too blurry"):
        sanitize_image(_blank(), "image/png")


def test_heavily_blurred_image_is_refused() -> None:
    with pytest.raises(ImageQualityError):
        sanitize_image(_blurry(), "image/png")


def test_tiny_image_is_refused() -> None:
    with pytest.raises(ImageQualityError, match="too small"):
        sanitize_image(_tiny(), "image/png")


def test_sharp_page_passes_and_reports_its_measurement() -> None:
    out = sanitize_image(base64.b64decode(base64.b64encode(_png_bytes())), "image/png")
    assert out.edge_std > MIN_EDGE_STD
    assert out.width == 400 and out.height == 300
    assert out.bytes_out > 0


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    _page().save(buffer, format="PNG")
    return buffer.getvalue()


def test_non_image_and_bad_base64_are_refused() -> None:
    with pytest.raises(ImageSanitizeError, match="could not be decoded"):
        sanitize_image(b"this is not an image", "image/png")
    with pytest.raises(ImageSanitizeError, match="unsupported image type"):
        sanitize_image(_png_bytes(), "image/svg+xml")
    with pytest.raises(ImageSanitizeError, match="valid base64"):
        sanitize_inline_image("image/png", "!!!!not-base64!!!!")


def test_zero_byte_payload_is_refused() -> None:
    with pytest.raises(ImageSanitizeError, match="empty image payload"):
        sanitize_image(b"", "image/png")


# ----------------------------------------------------------------- tutor ----
class _RecordingProvider:
    name = "recording"

    def __init__(self) -> None:
        self.calls = 0
        self.images: list[dict] = []

    async def generate(self, prompt, *, system=None, image=None, **kwargs):
        self.calls += 1
        self.images.append(image or {})
        return CHUNK_TEXT

    async def stream(self, prompt, *, system=None, image=None, **kwargs):
        self.calls += 1
        self.images.append(image or {})
        yield CHUNK_TEXT


class _Index:
    chunks: ClassVar[list[Chunk]] = []

    def search(self, query: str, **_kwargs) -> list[Hit]:
        return [
            Hit(
                chunk=Chunk(id="c1", meta=_meta(), text=CHUNK_TEXT),
                score=1.0,
            )
        ]


def _meta() -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="sample",
        chapter="অধ্যায় ১",
        section="কোষ",
        page=3,
    )


def _service(provider) -> TutorService:
    service = TutorService(index=_Index(), provider=provider, min_coverage=0.0, min_score=0.0)
    service.stream_heartbeat_seconds = 0
    return service


def _inline(raw: bytes, mime: str) -> dict:
    return {"mime_type": mime, "data": base64.b64encode(raw).decode("ascii")}


async def test_ask_sends_a_metadata_free_image_to_the_provider() -> None:
    provider = _RecordingProvider()
    raw = _hostile_jpeg()
    response = await _service(provider).ask(
        "এই ছবির প্রশ্নটির উত্তর দাও।", 6, "science", image=_inline(raw, "image/jpeg")
    )
    assert provider.calls == 1
    sent = provider.images[0]
    assert sent["mime_type"] == "image/jpeg"
    decoded = base64.b64decode(sent["data"])
    assert COMMENT_MARKER not in decoded and b"rag2-camera" not in decoded
    assert response.grounded is True


async def test_ask_refuses_a_blank_image_without_calling_the_provider() -> None:
    provider = _RecordingProvider()
    response = await _service(provider).ask(
        "এই ছবির প্রশ্নটির উত্তর দাও।", 6, "science", image=_inline(_blank(), "image/png")
    )
    assert provider.calls == 0
    assert response.grounded is False
    assert response.refused_reason == "image_unreadable"
    assert response.answer == IMAGE_UNREADABLE_ANSWER


async def test_ask_stream_refuses_a_blurry_image_without_calling_the_provider() -> None:
    provider = _RecordingProvider()
    events = [
        event
        async for event in _service(provider).ask_stream(
            "এই ছবির প্রশ্নটির উত্তর দাও।", 6, "science", image=_inline(_blurry(), "image/png")
        )
    ]
    assert provider.calls == 0
    assert events[-1].response is not None
    assert events[-1].response.refused_reason == "image_unreadable"


async def test_text_only_turns_are_untouched() -> None:
    provider = _RecordingProvider()
    response = await _service(provider).ask("কোষ কী?", 6, "science")
    assert provider.calls == 1
    assert provider.images[0] == {}
    assert response.grounded is True
