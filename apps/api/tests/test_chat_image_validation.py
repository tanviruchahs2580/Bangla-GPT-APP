"""S-011: chat images are validated by content, not by the client's label.

``_validate_chat_image`` accepted any bytes whose declared ``mime_type`` was
one of the allowed strings: a text blob labelled ``image/png`` was forwarded
unchanged to the third-party vision model, and so were GIF bytes. These tests
pin magic-byte sniffing plus the declared/sniffed match, at the unit level and
end to end through the chat route.

Since AUD-A2-17 the validator also decodes and re-encodes what it accepts, so
the bytes that leave the API are metadata-free (see
``test_image_metadata_stripping.py`` for that contract). Two consequences are
visible here: the accepted fixtures are real decodable images, and the payload
is a re-encode rather than a copy of the input.
"""

import base64
import io

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers.common import _validate_chat_image
from bangla_gpt_api.schemas import ChatImageIn
from conftest import engine_url

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"


def _real_image(fmt: str, size: tuple[int, int] = (48, 48)) -> bytes:
    """A decodable fixture: since AUD-A2-17 the validator decodes what it takes."""
    buf = io.BytesIO()
    Image.new("RGB", size, (180, 120, 60)).save(buf, format=fmt)
    return buf.getvalue()


# 1x1 transparent PNG (a real, decodable image).
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
JPEG = _real_image("JPEG")
WEBP = _real_image("WEBP")
GIF = b"GIF89a" + b"\x00" * 16
TEXT = b"this is not an image, just text"


def _image(mime: str, raw: bytes) -> ChatImageIn:
    return ChatImageIn(mime_type=mime, data_base64=base64.b64encode(raw).decode())


def _code(exc: HTTPException) -> str:
    return str(exc.detail["code"])  # type: ignore[index]


# --- unit level ---------------------------------------------------------------


def test_valid_png_is_accepted() -> None:
    out = _validate_chat_image(_image("image/png", TINY_PNG))
    assert out is not None
    assert out["mime_type"] == "image/png"
    # a re-encode, not a copy: the point is that nothing of the original file
    # (its metadata included) is forwarded
    with Image.open(io.BytesIO(base64.b64decode(out["data"]))) as clean:
        assert clean.format == "PNG"
        assert not dict(clean.getexif())


def test_valid_jpeg_and_webp_are_accepted() -> None:
    assert _validate_chat_image(_image("image/jpeg", JPEG))["mime_type"] == "image/jpeg"  # type: ignore[index]
    # WebP is re-encoded: PNG keeps transparency, JPEG does not, and an opaque
    # photo is far smaller as JPEG (see image_safety._output_format).
    assert _validate_chat_image(_image("image/webp", WEBP))["mime_type"] == "image/jpeg"  # type: ignore[index]


def test_text_labelled_png_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_chat_image(_image("image/png", TEXT))
    assert exc.value.status_code == 422
    assert _code(exc.value) == "image_type_mismatch"


def test_gif_bytes_labelled_png_are_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_chat_image(_image("image/png", GIF))
    assert exc.value.status_code == 422
    assert _code(exc.value) == "image_type_mismatch"


def test_png_bytes_labelled_jpeg_are_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_chat_image(_image("image/jpeg", TINY_PNG))
    assert exc.value.status_code == 422
    assert _code(exc.value) == "image_type_mismatch"


def test_oversize_still_rejected_with_image_invalid() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_chat_image(_image("image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 1_600_000))
    assert exc.value.status_code == 422
    assert _code(exc.value) == "image_invalid"


def test_disallowed_mime_still_rejected_with_image_invalid() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_chat_image(_image("image/gif", GIF))
    assert exc.value.status_code == 422
    assert _code(exc.value) == "image_invalid"


def test_undecodable_base64_still_rejected_with_image_invalid() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_chat_image(ChatImageIn(mime_type="image/png", data_base64="!!!not-base64!!!"))
    assert exc.value.status_code == 422
    assert _code(exc.value) == "image_invalid"


def test_empty_payload_is_rejected_by_the_schema() -> None:
    # The request model already refuses an empty data_base64 (min_length=1),
    # so the helper's empty branch is unreachable defence in depth.
    with pytest.raises(ValidationError):
        _image("image/png", b"")


def test_no_image_is_none() -> None:
    assert _validate_chat_image(None) is None


# --- end to end through the chat route ----------------------------------------


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "image"),
        jwt_secret=JWT,
    )
    return TestClient(create_app(settings))


def _conversation_and_headers(client: TestClient) -> tuple[int, dict]:
    res = client.post(
        "/auth/register",
        json={
            "email": "kid@example.test",
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "kid@example.test", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    conv = client.post("/tutor/conversations", json={}, headers=headers)
    assert conv.status_code == 201, conv.text
    return int(conv.json()["id"]), headers


def test_chat_route_rejects_text_labelled_png(client: TestClient) -> None:
    conv_id, headers = _conversation_and_headers(client)
    res = client.post(
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={
            "message": "what is in this picture",
            "image": {"mime_type": "image/png", "data_base64": base64.b64encode(TEXT).decode()},
        },
        headers=headers,
    )
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["code"] == "image_type_mismatch"


def test_chat_route_accepts_a_real_png(client: TestClient) -> None:
    conv_id, headers = _conversation_and_headers(client)
    res = client.post(
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={
            "message": "what is in this picture",
            "image": {"mime_type": "image/png", "data_base64": base64.b64encode(TINY_PNG).decode()},
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
