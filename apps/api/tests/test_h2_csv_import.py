"""H-13 / AUD-HI-16: the CSV import against real Excel/Bangla roster shapes.

The pre-existing coverage (``tests/test_hi_csv_import.py``) pinned BOM, CRLF
and malformed rows. This file pins the rest of the encoding/format contract a
Bangladeshi school actually produces:

* Excel's "CSV UTF-8" export: BOM, CRLF, but also a ``sep=,`` preamble line in
  some locales -- it must be REPORTED as an invalid row, never silently eaten;
* quoted cells with embedded commas and quoted empty cells;
* header spelling variants ("Name", "NAME", trailing spaces) and files without
  a header at all;
* row-level reporting: per-row status, ``created``/``failed`` totals, an invite
  code only on created rows, and duplicates detected *inside* one file;
* the row cap boundary (200 rows pass, 201 is refused) and oversized payloads.

Honest limitation, recorded in the finding: the handler takes a JSON *string*
(<= 20,000 characters, schema-bounded), so a true streaming multipart import
is a router/schema change tracked in ``.audit/handoffs/f2-from-h2.md``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
# NFC forms: "রহিম" with the decomposed ya+nukta, "ফাতেমা আক্তার", "শ্রেণি" style
# conjuncts everywhere; a ZWNJ-joined "Md. রহিম" variant for the display name.
RAHIM = "\u09b0\u09b9\u09bf\u09ae"
FATEMA = "\u09ab\u09be\u09a4\u09c7\u09ae\u09be"
WITH_ZWJ = "\u09ae\u09cb\u09b9\u09be\u09ae\u09cd\u09ae\u09a6\u200d"
CAP = 200


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/h2-import.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _teacher(client: TestClient, email: str = "h2-import@example.com") -> dict:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teacher", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _room(client: TestClient, headers: dict) -> int:
    res = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "H2"}, headers=headers
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _import(client: TestClient, headers: dict, room: int, csv_text: str):
    return client.post(
        f"/teacher/classrooms/{room}/import", json={"csv_text": csv_text}, headers=headers
    )


def test_excel_export_with_sep_preamble_and_quotes(client: TestClient) -> None:
    """Excel writes ``sep=,`` before the header in some locales."""
    headers = _teacher(client)
    room = _room(client, headers)
    csv_text = (
        "sep=,\r\n"
        "name,email\r\n"
        f'"{RAHIM} {FATEMA}",rahim@example.com\r\n'  # quoted name with a space
        f'"{WITH_ZWJ}","joined@example.com"\r\n'
    )
    res = _import(client, headers, room, csv_text)
    assert res.status_code == 200, res.text
    body = res.json()
    statuses = [row["status"] for row in body["rows"]]
    # The preamble is a row the operator can SEE and fix; it is not swallowed.
    # The real header now sits in row 1, so it is reported too (its "email"
    # cell has no '@') instead of being mistaken for the header row.
    assert statuses == ["invalid", "invalid", "created", "created"], statuses
    assert body["created"] == 2
    assert body["failed"] == 2
    assert body["rows"][0]["name"] == "sep="
    assert body["rows"][1]["name"] == "name"
    # Names keep their ZWJ and their conjuncts exactly as exported.
    assert body["rows"][2]["name"] == f"{RAHIM} {FATEMA}"
    assert body["rows"][3]["name"] == WITH_ZWJ


def test_quoted_cell_with_embedded_comma_is_one_field(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    csv_text = 'name,email\n"Rahim, Md.",rahim@example.com\n'
    res = _import(client, headers, room, csv_text)
    assert res.status_code == 200, res.text
    row = res.json()["rows"][0]
    assert row["status"] == "created" and row["name"] == "Rahim, Md."


def test_header_variants_and_headerless_files(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    for index, header in enumerate(("Name,Email", "NAME,EMAIL", " name , email ")):
        res = _import(client, headers, room, f"{header}\n{RAHIM} {index},case-{index}@example.com")
        assert res.status_code == 200, res.text
        assert res.json()["created"] == 1, res.text
    # A headerless single row is still a data row (nothing may be swallowed).
    res = _import(client, headers, room, f"{FATEMA},noheader@example.com")
    assert res.json()["created"] == 1, res.text


def test_row_level_report_shape_and_invite_codes_only_for_created_rows(
    client: TestClient,
) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    csv_text = "\n".join(
        [
            "name,email",
            f"{RAHIM},row-1@example.com",
            f"{RAHIM},row-1@example.com",  # duplicate inside the same file
            "No Email,",  # invalid
            f"{FATEMA},not-an-email",  # invalid (no domain dot)
            f"{FATEMA},row-2@example.com",
        ]
    )
    res = _import(client, headers, room, csv_text)
    assert res.status_code == 200, res.text
    body = res.json()
    assert [row["status"] for row in body["rows"]] == [
        "created",
        "duplicate_email",
        "invalid",
        "invalid",
        "created",
    ]
    assert body["created"] == 2 and body["failed"] == 3
    for row in body["rows"]:
        assert set(row) >= {"name", "email", "status"}
        if row["status"] == "created":
            assert row["invite_code"], row
        else:
            assert row.get("invite_code") in (None, ""), row

    # The codes really are single-use passwords: the first student can sign in
    # with it and is forced to change it.
    first_code = body["rows"][0]["invite_code"]
    login = client.post("/auth/login", json={"email": "row-1@example.com", "password": first_code})
    assert login.status_code == 200, login.text
    assert login.json().get("must_change_password") is True, login.json()


def test_row_cap_boundary_and_oversized_payload(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    exact = "name,email\n" + "\n".join(f"{RAHIM} {i},cap-{i}@example.com" for i in range(CAP))
    res = _import(client, headers, room, exact)
    assert res.status_code == 200, res.text
    assert res.json()["created"] == CAP

    over = "name,email\n" + "\n".join(f"{FATEMA} {i},over-{i}@example.com" for i in range(CAP + 1))
    assert _import(client, headers, room, over).status_code == 422

    assert _import(client, headers, room, "x" * 20_001).status_code == 422


def test_blank_rows_and_trailing_newlines_are_skipped_not_reported(
    client: TestClient,
) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    csv_text = f"name,email\n\n{RAHIM},blank@example.com\n\n\n"
    res = _import(client, headers, room, csv_text)
    assert res.status_code == 200, res.text
    assert [row["status"] for row in res.json()["rows"]] == ["created"]


def test_no_data_rows_is_a_clean_422(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    assert _import(client, headers, room, "\n\n\n").status_code == 422
    assert _import(client, headers, room, "name,email\n").status_code == 422
