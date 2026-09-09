"""Wave 2 API contracts: strategy + inline-image chat, answer confidence,
whitelisted student prefs, soft memory opt-out, window reports (parent +
student self view) and the admin AI-quality panel shape.

ASCII only (R11 house rule for new API tests). Mock provider only -- this
file must never reach a real Gemini quota.
"""

import base64

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
# 1x1 transparent PNG (decodes to ~70 bytes: far under the 1.5 MB cap).
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/wave2.db",
        jwt_secret=SECRET,
        allow_direct_parent_link=True,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
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


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _student(client: TestClient, email: str = "kid@example.com") -> dict:
    _register(client, email)
    return _login(client, email)


def _conversation(client: TestClient, headers: dict) -> int:
    res = client.post("/tutor/conversations", json={}, headers=headers)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


# --- student preferences -----------------------------------------------------


def test_prefs_defaults_and_whitelist(client: TestClient) -> None:
    kid = _student(client)
    res = client.get("/students/me/prefs", headers=kid)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["memory_enabled"], bool)
    assert isinstance(body["learning_prefs"], dict)

    res = client.patch(
        "/students/me/prefs",
        json={"learning_prefs": {"explanation_style": "detailed", "subject_focus": "geometry"}},
        headers=kid,
    )
    assert res.status_code == 200
    assert res.json()["learning_prefs"]["explanation_style"] == "detailed"

    # bad enum value is a hard 422 (whitelist contract).
    res = client.patch(
        "/students/me/prefs",
        json={"learning_prefs": {"explanation_style": "chaos"}},
        headers=kid,
    )
    assert res.status_code == 422

    # unknown key is a hard 422 -- no client can smuggle arbitrary state.
    res = client.patch(
        "/students/me/prefs",
        json={"learning_prefs": {"sudo": True}},
        headers=kid,
    )
    assert res.status_code == 422

    # teachers never own student prefs.
    _register(client, "teach@example.com", role="teacher")
    teach = _login(client, "teach@example.com")
    assert client.get("/students/me/prefs", headers=teach).status_code == 403


def test_memory_soft_optout_returns_disable_note_code(client: TestClient) -> None:
    kid = _student(client)
    res = client.get("/students/me/memory", headers=kid)
    assert res.status_code == 200
    body = res.json()
    assert body["memory_enabled"] is True
    assert isinstance(body["facts"], dict)
    assert body["on_disable_note_code"] == "memory_on_disable_note"

    res = client.delete("/students/me/memory", headers=kid)
    assert res.status_code == 200
    assert res.json()["memory_enabled"] is False

    res = client.get("/students/me/memory", headers=kid)
    assert res.json()["memory_enabled"] is False


# --- chat strategy + inline image + confidence --------------------------------


def test_ask_carries_confidence_field(client: TestClient) -> None:
    kid = _student(client)
    res = client.post(
        "/tutor/ask",
        json={"question": "why do seasons change", "class_level": 6},
        headers=kid,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "confidence" in body
    assert body["confidence"] is None or 0.0 <= float(body["confidence"]) <= 1.0


def test_chat_strategy_literal_validation(client: TestClient) -> None:
    kid = _student(client)
    conv = _conversation(client, kid)
    res = client.post(
        f"/tutor/conversations/{conv}/messages/stream",
        json={"message": "explain photosynthesis", "strategy": "not-a-strategy"},
        headers=kid,
    )
    assert res.status_code == 422

    res = client.post(
        f"/tutor/conversations/{conv}/messages/stream",
        json={"message": "explain photosynthesis", "strategy": "steps"},
        headers=kid,
    )
    assert res.status_code == 200
    assert "data:" in res.text or "event" in res.text


def test_chat_image_mime_and_size_are_rejected(client: TestClient) -> None:
    kid = _student(client)
    conv = _conversation(client, kid)

    res = client.post(
        f"/tutor/conversations/{conv}/messages/stream",
        json={
            "message": "what is in this picture",
            "image": {"mime_type": "application/pdf", "data_base64": TINY_PNG_B64},
        },
        headers=kid,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "image_invalid"

    huge = base64.b64encode(b"0" * 1_600_000).decode()
    res = client.post(
        f"/tutor/conversations/{conv}/messages/stream",
        json={
            "message": "what is in this picture",
            "image": {"mime_type": "image/png", "data_base64": huge},
        },
        headers=kid,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "image_invalid"

    # a valid small png passes validation (mock provider answers).
    res = client.post(
        f"/tutor/conversations/{conv}/messages/stream",
        json={
            "message": "what is in this picture",
            "image": {"mime_type": "image/png", "data_base64": TINY_PNG_B64},
        },
        headers=kid,
    )
    assert res.status_code == 200


# --- window reports -----------------------------------------------------------


def _link_parent(client: TestClient) -> tuple:
    kid = _student(client)
    code = client.post("/students/me/invite-code", headers=kid).json()["code"]
    _register(client, "mom@example.com", role="parent")
    mom = _login(client, "mom@example.com")
    res = client.post("/parents/link/invite", json={"code": code}, headers=mom)
    assert res.status_code == 201, res.text
    children = client.get("/parents/me/children", headers=mom).json()
    return kid, mom, int(children[0]["student_id"])


def test_parent_report_window_shape(client: TestClient) -> None:
    _, mom, sid = _link_parent(client)
    res = client.get(f"/parents/me/children/{sid}/report?period=weekly", headers=mom)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["period"] == "weekly"
    assert body["student_id"] == sid
    for key in (
        "quizzes_taken",
        "quizzes_graded",
        "chapters_read",
        "chapters_completed",
        "questions_asked",
    ):
        assert isinstance(body[key], int)
    assert body["weak_chapters"] == [] and body["strengths"] == []
    assert body["suggestion_code"] == "sugg_no_activity"


def test_student_self_report_matches_parent_view(client: TestClient) -> None:
    kid, mom, sid = _link_parent(client)
    mine = client.get("/students/me/report?period=monthly", headers=kid)
    theirs = client.get(f"/parents/me/children/{sid}/report?period=monthly", headers=mom)
    assert mine.status_code == 200, mine.text
    assert theirs.status_code == 200
    assert mine.json()["student_id"] == theirs.json()["student_id"]
    assert mine.json()["period"] == "monthly"

    _register(client, "teach@example.com", role="teacher")
    teach = _login(client, "teach@example.com")
    assert client.get("/students/me/report", headers=teach).status_code == 403


# --- admin AI quality ---------------------------------------------------------


def test_admin_ai_quality_shape(client: TestClient) -> None:
    root = _login(client, "root@example.com")
    kid = _student(client)
    conv = _conversation(client, kid)
    # one real chat turn persists assistant ChatMessage rows -- the panel's
    # counting source (/tutor/ask is stateless and must NOT appear here).
    res = client.post(
        f"/tutor/conversations/{conv}/messages/stream",
        json={"message": "explain photosynthesis"},
        headers=kid,
    )
    assert res.status_code == 200
    res = client.get("/admin/ai/quality?days=30", headers=root)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["days"] == 30
    assert body["answers_total"] >= 1
    assert body["grounded_count"] + body["ungrounded_count"] <= body["answers_total"]
    for key in ("refusals_by_reason", "by_model"):
        assert isinstance(body[key], dict)
    for key in ("refusals_total", "thumbs_up", "thumbs_down", "low_confidence_count"):
        assert isinstance(body[key], int)
