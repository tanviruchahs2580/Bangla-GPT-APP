"""R3 / WS3 H-13: the CSV roster import accepts a real uploaded file.

``tests/test_h2_csv_import.py`` pins the paste-text JSON path; this file pins
the file-upload sibling added in ``routers/class_import.py``:

* a UTF-8 file with BOM (Excel's "CSV UTF-8") and CRLF;
* Excel's "Unicode text" export (UTF-16 with BOM, tab-free CSV);
* the byte cap (413) and the shared 20,000-character contract (413);
* hostile/empty/wrong-typed bodies (422/415), never a 500;
* delegation: the same bytes through both routes produce the same rows, so
  row-level reporting, dedupe and the transaction cannot diverge.
"""

from __future__ import annotations

import codecs

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers.class_import import IMPORT_MAX_BYTES

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
RAHIM = "\u09b0\u09b9\u09bf\u09ae"
FATEMA = "\u09ab\u09be\u09a4\u09c7\u09ae\u09be"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/r3-import.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _teacher(client: TestClient, email: str = "r3-import@example.com") -> dict:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teacher", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _room(client: TestClient, headers: dict) -> int:
    res = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "W3"}, headers=headers
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _upload(
    client: TestClient,
    headers: dict,
    room: int,
    payload: bytes,
    content_type: str = "text/csv",
):
    return client.post(
        f"/teacher/classrooms/{room}/import-file",
        content=payload,
        headers={**headers, "Content-Type": content_type},
    )


def test_utf8_bom_file_with_bangla_names_creates_rows(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    body = (
        codecs.BOM_UTF8
        + (
            f"name,email\r\n{RAHIM} {FATEMA},rahim@example.com\r\n{FATEMA},fatema@example.com\r\n"
        ).encode()
    )
    res = _upload(client, headers, room, body)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["created"] == 2
    assert [row["status"] for row in out["rows"]] == ["created", "created"]
    assert out["rows"][0]["name"] == f"{RAHIM} {FATEMA}"  # stored as given, BOM-free
    assert all(row["invite_code"] for row in out["rows"])


def test_excel_unicode_text_export_utf16_with_bom(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    body = (f"name,email\r\n{RAHIM},rahim16@example.com\r\n").encode("utf-16")  # BOM included
    res = _upload(client, headers, room, body)
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 1
    assert res.json()["rows"][0]["name"] == RAHIM


def test_an_upload_produces_the_same_rows_as_the_json_path(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    # Same shape through both routes (different emails so each run creates):
    # one valid row, one malformed row, one email repeated *inside* the file.
    json_csv = (
        "name,email\r\n"
        f"{RAHIM},json-path@example.com\r\n"
        "bad-row-without-email,\r\n"
        f"{FATEMA},JSON-PATH@example.com\r\n"
    )
    file_csv = (
        "name,email\r\n"
        f"{RAHIM},file-path@example.com\r\n"
        "bad-row-without-email,\r\n"
        f"{FATEMA},FILE-PATH@example.com\r\n"
    )
    via_json = client.post(
        f"/teacher/classrooms/{room}/import", json={"csv_text": json_csv}, headers=headers
    )
    assert via_json.status_code == 200, via_json.text
    via_file = _upload(client, headers, room, file_csv.encode("utf-8"))
    assert via_file.status_code == 200, via_file.text
    expected = ["created", "invalid", "duplicate_email"]
    assert [row["status"] for row in via_json.json()["rows"]] == expected
    assert [row["status"] for row in via_file.json()["rows"]] == expected
    assert via_json.json()["created"] == via_file.json()["created"] == 1
    assert len(via_json.json()["rows"]) == len(via_file.json()["rows"])


def test_oversize_body_is_413_and_never_parsed(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    body = b"name,email\r\n" + b"x" * (IMPORT_MAX_BYTES + 1)
    res = _upload(client, headers, room, body)
    assert res.status_code == 413, res.text
    assert "too large" in res.json()["detail"]


def test_over_the_character_contract_is_413_even_under_the_byte_cap(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    # 20,001 ASCII characters: 20,001 bytes, far under IMPORT_MAX_BYTES but
    # over the shared character contract the JSON path enforces.
    body = b"name,email\r\n" + b"a" * 20_000
    res = _upload(client, headers, room, body)
    assert res.status_code == 413, res.text
    assert "characters" in res.json()["detail"]


@pytest.mark.parametrize(
    ("payload", "content_type", "status"),
    [
        (b"", "text/csv", 422),
        (b"\n\r\n \n", "text/csv", 422),
        (b"name,email\r\n\x80\x81x,y@z.com\r\n", "text/csv", 422),  # not UTF-8, no UTF-16 BOM
        (b"name,email\r\n", "application/json", 415),
        (b"name,email\r\n", "image/png", 415),
    ],
)
def test_bad_uploads_are_4xx_never_500(
    client: TestClient, payload: bytes, content_type: str, status: int
) -> None:
    headers = _teacher(client, email=f"r3-bad-{status}-{len(payload)}@example.com")
    room = _room(client, headers)
    res = _upload(client, headers, room, payload, content_type)
    assert res.status_code == status, res.text
    assert res.json()["detail"]
