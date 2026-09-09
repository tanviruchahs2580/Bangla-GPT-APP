"""Wave 1: in-app notification feed + the four event producers.

Codes: notif_quiz_assigned, notif_shorttest_assigned, notif_support_plan,
notif_parent_linked. Params carry ids/labels only (R11: no message copy).
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/notif.db",
        jwt_secret=SECRET,
        allow_direct_parent_link=True,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str = "student", **kw) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Person", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    payload.update(kw)
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _teacher(client: TestClient) -> dict:
    _register(client, "teach@example.com", role="teacher")
    return _login(client, "teach@example.com")


def _codes(client: TestClient, headers: dict) -> list:
    body = client.get("/notifications", headers=headers).json()
    return [n["code"] for n in body["items"]]


def test_quiz_assignment_notifies_each_student(client: TestClient) -> None:
    teach = _teacher(client)
    s1 = _register(client, "s1@example.com")
    s2 = _register(client, "s2@example.com")
    res = client.post(
        "/teacher/assignments",
        json={
            "student_ids": [s1["profile_id"], s2["profile_id"]],
            "subject": "science",
            "chapter": CHAPTER,
            "num_questions": 3,
            "due_at": "2030-01-01T00:00:00",
        },
        headers=teach,
    )
    assert res.status_code == 201, res.text
    assignment_id = res.json()["id"]

    for email in ("s1@example.com", "s2@example.com"):
        headers = _login(client, email)
        body = client.get("/notifications", headers=headers).json()
        assert "notif_quiz_assigned" in [n["code"] for n in body["items"]]
        assert body["unread_count"] >= 1
        note = next(n for n in body["items"] if n["code"] == "notif_quiz_assigned")
        assert note["kind"] == "assignment"
        assert note["params"]["assignment_id"] == assignment_id
        assert note["link"] == "/student/quiz"


def test_support_plan_notifies_student_user(client: TestClient) -> None:
    teach = _teacher(client)
    student = _register(client, "weak@example.com")
    headers = _login(client, "weak@example.com")
    started = client.post(
        "/quizzes", json={"student_id": student["profile_id"], "num_questions": 2}, headers=headers
    )
    assert started.status_code == 200, started.text
    answers = started.json()["questions"]
    client.post(
        f"/quizzes/{started.json()['attempt_id']}/submit",
        json={"answers": [0] * len(answers)},
        headers=headers,
    )
    res = client.post(
        "/teacher/support-plans",
        json={"student_id": student["profile_id"]},
        headers=teach,
    )
    assert res.status_code == 201, res.text
    assert "notif_support_plan" in _codes(client, headers)


def test_parent_link_notifies_both_sides(client: TestClient) -> None:
    student = _register(client, "kid@example.com")
    _register(client, "mum@example.com", role="parent")
    parent = _login(client, "mum@example.com")
    res = client.post("/parents/link", json={"student_id": student["profile_id"]}, headers=parent)
    assert res.status_code == 201, res.text
    assert "notif_parent_linked" in _codes(client, parent)
    kid = _login(client, "kid@example.com")
    assert "notif_parent_linked" in _codes(client, kid)


def test_feed_is_scoped_newest_first_and_read_state_idempotent(client: TestClient) -> None:
    teach = _teacher(client)
    s1 = _register(client, "only@example.com")
    _register(client, "other@example.com")
    for _ in range(2):
        res = client.post(
            "/teacher/assignments",
            json={
                "student_ids": [s1["profile_id"]],
                "subject": "science",
                "chapter": CHAPTER,
                "num_questions": 2,
                "due_at": "2030-01-01T00:00:00",
            },
            headers=teach,
        )
        assert res.status_code == 201, res.text

    mine = _login(client, "only@example.com")
    body = client.get("/notifications", headers=mine).json()
    assert len(body["items"]) == 2 and body["unread_count"] == 2
    # newest first
    assert body["items"][0]["id"] > body["items"][1]["id"]
    assert body["items"][0]["read_at"] is None

    first = body["items"][0]
    marked = client.post(f"/notifications/{first['id']}/read", headers=mine)
    assert marked.status_code == 200, marked.text
    assert marked.json()["read_at"] is not None
    again = client.post(f"/notifications/{first['id']}/read", headers=mine)
    assert again.json()["read_at"] == marked.json()["read_at"]

    body = client.get("/notifications", headers=mine).json()
    assert body["unread_count"] == 1

    # the other student cannot mark it read and never sees it
    theirs = _login(client, "other@example.com")
    assert client.post(f"/notifications/{first['id']}/read", headers=theirs).status_code == 404
    assert _codes(client, theirs) == []
    # teachers get no student-facing notifications
    assert _codes(client, teach) == []


def test_feed_requires_authentication(client: TestClient) -> None:
    assert client.get("/notifications").status_code == 401
    assert client.post("/notifications/1/read").status_code == 401


def test_shorttest_notifies_roster(client: TestClient) -> None:
    teach = _teacher(client)
    room = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "A"}, headers=teach
    )
    assert room.status_code == 201, room.text
    room_id = room.json()["id"]
    rows = "\n".join(f"Pupil {i},p{i}@school.edu" for i in range(2))
    imp = client.post(
        f"/teacher/classrooms/{room_id}/import",
        json={"csv_text": f"name,email\n{rows}"},
        headers=teach,
    )
    assert imp.status_code == 200, imp.text
    codes = [r["invite_code"] for r in imp.json()["rows"]]

    res = client.post(
        "/teacher/shorttests",
        json={
            "classroom_id": room_id,
            "subject": "science",
            "chapter": CHAPTER,
            "num_questions": 3,
            "duration_min": 10,
        },
        headers=teach,
    )
    assert res.status_code == 201, res.text

    # CSV-created accounts: log in with the invite code, then claim a password
    login = client.post("/auth/login", json={"email": "p0@school.edu", "password": codes[0]})
    assert login.status_code == 200, login.text
    tok = login.json()["access_token"]
    change = client.post(
        "/auth/change-password",
        json={"current_password": codes[0], "new_password": PASSWORD},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert change.status_code == 200, change.text
    headers = _login(client, "p0@school.edu")
    body = client.get("/notifications", headers=headers).json()
    assert "notif_shorttest_assigned" in [n["code"] for n in body["items"]]
