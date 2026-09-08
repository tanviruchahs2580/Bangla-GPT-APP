"""S2.2: classroom CRUD + CSV bulk import creating invite-linked accounts."""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/class.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str) -> None:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Teacher", "role": role}
    if role == "student":
        payload.update({"class_level": 6, "guardian_consent": True})
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text


def _headers(client: TestClient, email: str) -> dict[str, str]:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def teacher_headers(client: TestClient) -> dict[str, str]:
    _register(client, "teach@example.com", "teacher")
    return _headers(client, "teach@example.com")


def _create_room(client: TestClient, headers: dict, level: int = 6, section: str = "A") -> int:
    res = client.post(
        "/teacher/classrooms",
        json={"class_level": level, "section": section},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_classroom_create_list_unique(client: TestClient, teacher_headers) -> None:
    rid = _create_room(client, teacher_headers, 6, "A")
    rooms = client.get("/teacher/classrooms", headers=teacher_headers).json()
    assert [r["id"] for r in rooms] == [rid]
    assert rooms[0]["class_level"] == 6 and rooms[0]["section"] == "A"
    assert rooms[0]["student_count"] == 0
    # same school+level+section is rejected
    dup = client.post(
        "/teacher/classrooms",
        json={"class_level": 6, "section": "a"},  # section is normalized upper
        headers=teacher_headers,
    )
    assert dup.status_code == 409
    # a different section is fine
    assert (
        client.post(
            "/teacher/classrooms",
            json={"class_level": 6, "section": "B"},
            headers=teacher_headers,
        ).status_code
        == 201
    )


def test_csv_import_creates_invite_linked_accounts(client: TestClient, teacher_headers) -> None:
    rid = _create_room(client, teacher_headers)
    csv_text = (
        "name,email\n"
        "Rahim,rahim@school.edu\n"
        "Karim,karim@school.edu\n"
        "NoMail,nomail-not-an-email\n"
        "OnlyName\n"
    )
    res = client.post(
        f"/teacher/classrooms/{rid}/import",
        json={"csv_text": csv_text},
        headers=teacher_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] == 2 and body["failed"] == 2
    statuses = [r["status"] for r in body["rows"]]
    assert statuses == ["created", "created", "invalid", "invalid"]
    codes = [r["invite_code"] for r in body["rows"]]
    assert codes[0] and codes[1] and codes[0] != codes[1]
    assert codes[2] is None and codes[3] is None

    # roster reflects the enrollment with a pending invite
    roster = client.get(f"/teacher/classrooms/{rid}/roster", headers=teacher_headers).json()
    assert len(roster) == 2
    assert roster[0]["email"] == "rahim@school.edu"
    assert roster[0]["invite_pending"] is True
    assert roster[0]["class_level"] == 6

    # the invite code works as the initial password; login forces a change
    login = client.post("/auth/login", json={"email": "rahim@school.edu", "password": codes[0]})
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True


def test_import_rejects_duplicate_emails(client: TestClient, teacher_headers) -> None:
    rid = _create_room(client, teacher_headers)
    first = client.post(
        f"/teacher/classrooms/{rid}/import",
        json={"csv_text": "name,email\nAim,aim@school.edu\n"},
        headers=teacher_headers,
    ).json()
    assert first["created"] == 1
    second = client.post(
        f"/teacher/classrooms/{rid}/import",
        json={"csv_text": "name,email\nAim Again,aim@school.edu\nAim,Aim@SCHOOL.EDU\n"},
        headers=teacher_headers,
    ).json()
    # case-insensitive: stored lowercase, so Aim@SCHOOL.EDU is also a duplicate
    assert second["created"] == 0 and second["failed"] == 2
    assert {r["status"] for r in second["rows"]} == {"duplicate_email"}


def test_import_fourty_row_batch(client: TestClient, teacher_headers) -> None:
    """PASS-WHEN: 40-row CSV yields 40 invite-linked accounts."""
    rid = _create_room(client, teacher_headers, 7, "GEN")
    lines = ["name,email"] + [f"Student {i},s{i}@school.edu" for i in range(40)]
    res = client.post(
        f"/teacher/classrooms/{rid}/import",
        json={"csv_text": "\n".join(lines)},
        headers=teacher_headers,
    ).json()
    assert res["created"] == 40 and res["failed"] == 0
    assert all(r["invite_code"] for r in res["rows"])
    roster = client.get(f"/teacher/classrooms/{rid}/roster", headers=teacher_headers).json()
    assert len(roster) == 40
    rooms = client.get("/teacher/classrooms", headers=teacher_headers).json()
    assert [r for r in rooms if r["id"] == rid][0]["student_count"] == 40
    # one of the codes can actually sign in
    code = res["rows"][9]["invite_code"]
    login = client.post("/auth/login", json={"email": "s9@school.edu", "password": code})
    assert login.status_code == 200 and login.json()["must_change_password"] is True


def test_import_validation_and_authz(client: TestClient, teacher_headers) -> None:
    rid = _create_room(client, teacher_headers)
    empty = client.post(
        f"/teacher/classrooms/{rid}/import",
        json={"csv_text": "name,email\n"},
        headers=teacher_headers,
    )
    assert empty.status_code == 422
    too_big = "\n".join(["name,email"] + [f"n{i},n{i}@e.com" for i in range(201)])
    big = client.post(
        f"/teacher/classrooms/{rid}/import",
        json={"csv_text": too_big},
        headers=teacher_headers,
    )
    assert big.status_code == 422
    missing_room = client.get("/teacher/classrooms/999/roster", headers=teacher_headers)
    assert missing_room.status_code == 404

    _register(client, "kid@example.com", "student")
    kid = _headers(client, "kid@example.com")
    assert client.get("/teacher/classrooms", headers=kid).status_code == 403
    assert (
        client.post(
            f"/teacher/classrooms/{rid}/import",
            json={"csv_text": "a,b@c.com"},
            headers=kid,
        ).status_code
        == 403
    )
