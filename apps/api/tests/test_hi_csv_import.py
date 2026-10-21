"""H-13 / AUD-HI-16: the CSV import path with Bangla names and hostile input.

The pre-existing import tests used ASCII names and clean input only. This file
pins the encoding contract (UTF-8 text, BOM tolerated) and the malformed-row
behaviour, because a school's real roster export is Excel-produced, is Bangla,
and contains blank and duplicate rows.

Bengali literals are Unicode escapes only (house rule for API tests).
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
# "রহিম উদ্দিন" and "ফাতেমা আক্তার" -- ordinary Bangla names with conjuncts.
NAME_RAHIM = "\u09b0\u09b9\u09bf\u09ae \u0989\u09a6\u09cd\u09a6\u09bf\u09a8"
NAME_FATEMA = "\u09ab\u09be\u09a4\u09c7\u09ae\u09be \u0986\u0995\u09cd\u09a4\u09be\u09b0"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/hi-import.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _teacher(client: TestClient, email: str = "hi-teach@example.com") -> dict:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teacher", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _room(client: TestClient, headers: dict) -> int:
    res = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "HI"}, headers=headers
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _import(client: TestClient, headers: dict, room: int, csv_text: str):
    return client.post(
        f"/teacher/classrooms/{room}/import", json={"csv_text": csv_text}, headers=headers
    )


def test_bangla_names_round_trip_with_bom_and_crlf(client: TestClient) -> None:
    """Excel's "CSV UTF-8" file: BOM + CRLF + Bangla names."""
    headers = _teacher(client)
    room = _room(client, headers)
    csv_text = (
        "\ufeffname,email\r\n"
        f"{NAME_RAHIM},rahim@example.com\r\n"
        f"{NAME_FATEMA},fatema@example.com\r\n"
    )
    res = _import(client, headers, room, csv_text)
    assert res.status_code == 200, res.text
    rows = res.json()["rows"]
    assert [row["status"] for row in rows] == ["created", "created"]
    # The BOM must not survive into the first student's name.
    assert rows[0]["name"] == NAME_RAHIM
    assert "\ufeff" not in rows[0]["name"]
    assert rows[1]["name"] == NAME_FATEMA

    students = client.get("/teacher/students?class_level=6", headers=headers)
    assert students.status_code == 200, students.text
    names = {row["name"] for row in students.json()}
    assert {NAME_RAHIM, NAME_FATEMA} <= names, names


def test_malformed_rows_are_reported_not_imported(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    csv_text = "\n".join(
        [
            "name,email",
            f"{NAME_RAHIM},rahim@example.com",  # created
            "No Email,",  # missing email
            "Bad Domain,bad@localhost",  # no dot in domain
            f"{NAME_FATEMA},rahim@example.com",  # duplicate of the first row
            ",ghost@example.com",  # missing name
            "",  # blank line, must be skipped rather than reported
            f"{NAME_FATEMA},fatema@example.com",  # created
        ]
    )
    res = _import(client, headers, room, csv_text)
    assert res.status_code == 200, res.text
    body = res.json()
    statuses = [row["status"] for row in body["rows"]]
    assert statuses == ["created", "invalid", "invalid", "duplicate_email", "invalid", "created"], (
        statuses
    )
    assert body["created"] == 2
    assert body["failed"] == len(body["rows"]) - 2


def test_headerless_rows_are_accepted(client: TestClient) -> None:
    """Some exports have no header; the first row must not be swallowed."""
    headers = _teacher(client)
    room = _room(client, headers)
    res = _import(client, headers, room, f"{NAME_RAHIM},rahim@example.com")
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 1


def test_oversized_payload_is_refused_by_the_schema(client: TestClient) -> None:
    """The 20,000-character field bound is the documented payload cap."""
    headers = _teacher(client)
    room = _room(client, headers)
    res = _import(client, headers, room, "x" * 20_001)
    assert res.status_code == 422, res.text


def test_row_cap_is_enforced(client: TestClient) -> None:
    headers = _teacher(client)
    room = _room(client, headers)
    rows = [f"Name {i},student{i}@example.com" for i in range(201)]
    res = _import(client, headers, room, "name,email\n" + "\n".join(rows))
    assert res.status_code == 422
    assert "max" in res.text
