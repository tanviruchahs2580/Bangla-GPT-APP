"""S-011: chat images are validated by content, not by the client's label.

``_validate_chat_image`` accepted any bytes whose declared ``mime_type`` was
one of the allowed strings: a text blob labelled ``image/png`` was forwarded
unchanged to the third-party vision model, and so were GIF bytes. These tests
pin magic-byte sniffing (stdlib only) plus the declared/sniffed match, at the
unit level and end to end through the chat route.
"""

import base64

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers._image_contract import _validate_chat_image
from bangla_gpt_api.schemas import ChatImageIn

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"

# 1x1 transparent PNG.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP = b"RIFF" + (16).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 8
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
    assert base64.b64decode(out["data"]) == TINY_PNG


def test_valid_jpeg_and_webp_are_accepted() -> None:
    assert _validate_chat_image(_image("image/jpeg", JPEG))["mime_type"] == "image/jpeg"  # type: ignore[index]
    assert _validate_chat_image(_image("image/webp", WEBP))["mime_type"] == "image/webp"  # type: ignore[index]


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
        database_url=f"sqlite:///{tmp_path}/image.db",
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
