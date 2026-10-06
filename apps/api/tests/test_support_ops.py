"""support-ops tests.

PASS-WHEN halves:
* triage flow works -- user feedback lands in the admin queue oldest-first,
  a triage transition (with internal note) removes it from the open view,
  open_count stays truthful, and non-admins never see the queue;
* impersonation writes audit entries AND is now revocable -- the holder
  ends the session via POST /auth/impersonate/exit and the very same
  token is rejected immediately after (jti lands in the shared cache).
Plus the public /status payload shape (booleans/presence only, ).

New file kept ASCII-only (repo rule for new files).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.caching import CacheUnavailable
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AuditLog, ChatMessage, Conversation
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def pair(tmp_path):
    """Client + session factory over the SAME sqlite file (seed/assert directly)."""
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/support.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    factory = make_session_factory(make_engine(settings))
    return client, factory


def _register(client: TestClient, email: str, role: str = "student") -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Tester", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _admin_headers(client: TestClient) -> dict:
    return _login(client, "root@example.com")


def _seed_message(factory, student_profile_id: int, content: str) -> int:
    """A conversation + assistant message seeded directly, to give
    /feedback a real target without driving the whole tutor pipeline."""
    db = factory()
    try:
        conv = Conversation(student_id=student_profile_id, title="triage seed")
        db.add(conv)
        db.flush()
        msg = ChatMessage(conversation_id=conv.id, role="assistant", content=content)
        db.add(msg)
        db.commit()
        return msg.id
    finally:
        db.close()


# ---------------------------------------------------------------- status


def test_status_public_ok_shape(pair) -> None:
    client, _ = pair
    res = client.get("/status")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    names = {c["name"] for c in body["components"]}
    assert {"database", "cache", "assistant"} <= names
    for comp in body["components"]:
        assert isinstance(comp["ok"], bool)
        assert isinstance(comp["detail"], str)
    assert body["checked_at"]


def test_status_reports_degraded_when_cache_fails(pair) -> None:
    client, _ = pair
    app = client.app  # TestClient exposes the ASGI app
    app.state.cache.ping = lambda: False
    body = client.get("/status").json()
    assert body["status"] == "degraded"
    cache = [c for c in body["components"] if c["name"] == "cache"][0]
    assert cache["ok"] is False


# ---------------------------------------------------------- feedback queue


def test_feedback_queue_is_admin_only(pair) -> None:
    client, _ = pair
    _register(client, "t@example.com", role="teacher")
    teacher = _login(client, "t@example.com")
    assert client.get("/admin/feedback").status_code == 401
    assert client.get("/admin/feedback", headers=teacher).status_code == 403
    denied = client.patch("/admin/feedback/1", json={"triaged": True}, headers=teacher)
    assert denied.status_code == 403
    admin = _admin_headers(client)
    assert client.get("/admin/feedback?status=bogus", headers=admin).status_code == 422


def test_feedback_triage_flow_end_to_end(pair) -> None:
    client, factory = pair
    me = _register(client, "s@example.com")
    student = _login(client, "s@example.com")
    mid_a = _seed_message(factory, me["profile_id"], "answer one")
    mid_b = _seed_message(factory, me["profile_id"], "answer two")

    r1 = client.post(
        "/feedback",
        json={"message_id": mid_a, "rating": -1, "comment": "answer was confusing"},
        headers=student,
    )
    assert r1.status_code == 201, r1.text
    r2 = client.post(
        "/feedback",
        json={"message_id": mid_b, "rating": 1},
        headers=student,
    )
    assert r2.status_code == 201, r2.text

    admin = _admin_headers(client)
    queue = client.get("/admin/feedback", headers=admin).json()
    assert queue["total"] == 2 and queue["open_count"] == 2
    ids = [row["id"] for row in queue["rows"]]
    assert ids == sorted(ids)  # oldest first
    first = queue["rows"][0]
    assert first["rating"] == -1
    assert first["comment"] == "answer was confusing"
    assert first["role"] == "student"
    assert first["user_id"] == me["user_id"]
    assert first["triaged"] is False and first["note"] is None
    assert "email" not in first and "name" not in first  # complaint, not identity

    triaged = client.patch(
        f"/admin/feedback/{first['id']}",
        json={"triaged": True, "note": "rephrased lesson, shipped"},
        headers=admin,
    )
    assert triaged.status_code == 200
    row = triaged.json()
    assert row["triaged"] is True
    assert row["triaged_at"] is not None
    assert row["note"] == "rephrased lesson, shipped"

    open_q = client.get("/admin/feedback", headers=admin).json()
    assert open_q["total"] == 1 and open_q["open_count"] == 1
    assert [r["id"] for r in open_q["rows"]] == [ids[1]]
    all_q = client.get("/admin/feedback?status=all", headers=admin).json()
    assert all_q["total"] == 2
    assert all(r["note"] is None for r in all_q["rows"] if r["id"] != first["id"])

    # Un-triaging clears triaged_at but keeps the note (no evidence loss).
    back = client.patch(f"/admin/feedback/{first['id']}", json={"triaged": False}, headers=admin)
    assert back.status_code == 200
    assert back.json()["triaged"] is False
    assert back.json()["triaged_at"] is None
    assert back.json()["note"] == "rephrased lesson, shipped"


def test_feedback_triage_validation(pair) -> None:
    client, factory = pair
    me = _register(client, "s@example.com")
    student = _login(client, "s@example.com")
    mid = _seed_message(factory, me["profile_id"], "answer")
    client.post("/feedback", json={"message_id": mid, "rating": 1}, headers=student)
    admin = _admin_headers(client)
    fid = client.get("/admin/feedback", headers=admin).json()["rows"][0]["id"]
    missing = client.patch("/admin/feedback/99999", json={"triaged": True}, headers=admin)
    assert missing.status_code == 404
    assert (
        client.patch(
            f"/admin/feedback/{fid}", json={"triaged": True, "note": "x" * 501}, headers=admin
        ).status_code
        == 422
    )


# -------------------------------------------------- impersonation revoke


def _impersonate(client: TestClient, admin: dict, user_id: int) -> str:
    res = client.post(
        f"/admin/users/{user_id}/impersonate",
        json={"reason": "reproducing lesson bug"},
        headers=admin,
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def test_impersonation_exit_revokes_token_and_audits(pair) -> None:
    client, _ = pair
    me = _register(client, "s@example.com")
    admin = _admin_headers(client)
    imp_token = _impersonate(client, admin, me["user_id"])
    imp = {"Authorization": f"Bearer {imp_token}"}

    # The impersonation token works before exit...
    assert client.get("/users/me", headers=imp).status_code == 200
    # ...the holder ends the session (needs the impersonated user's identity)...
    assert client.post("/auth/impersonate/exit", headers=imp).status_code == 204
    # ...and the very same token is dead now, long before its 15-min expiry.
    assert client.get("/users/me", headers=imp).status_code == 401

    audit = client.get("/admin/audit?action=impersonation", headers=admin).json()
    phases = [row["detail"].get("phase") for row in audit["rows"]]
    assert "start" in phases and "exit" in phases
    exit_rows = [row for row in audit["rows"] if row["detail"].get("phase") == "exit"]
    assert exit_rows[0]["target"] == f"user:{me['user_id']}"
    assert exit_rows[0]["detail"].get("imp_by") is not None


def test_impersonation_exit_rejects_plain_tokens(pair) -> None:
    client, _ = pair
    _register(client, "s@example.com")
    student = _login(client, "s@example.com")
    res = client.post("/auth/impersonate/exit", headers=student)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "not_impersonation"
    assert client.post("/auth/impersonate/exit").status_code == 401


def test_impersonation_revocation_is_per_session(pair) -> None:
    client, factory = pair
    # Two students, two impersonation sessions: ending one must not end the other.

    a = _register(client, "a@example.com")
    b = _register(client, "b@example.com")
    assert a["user_id"] != b["user_id"]
    admin = _admin_headers(client)
    tok_a = _impersonate(client, admin, a["user_id"])
    tok_b = _impersonate(client, admin, b["user_id"])
    hdr_a = {"Authorization": f"Bearer {tok_a}"}
    hdr_b = {"Authorization": f"Bearer {tok_b}"}
    assert client.post("/auth/impersonate/exit", headers=hdr_a).status_code == 204
    assert client.get("/users/me", headers=hdr_a).status_code == 401
    assert client.get("/users/me", headers=hdr_b).status_code == 200
    # The real student's own token is untouched by any of this.
    assert client.get("/users/me", headers=_login(client, "a@example.com")).status_code == 200


# --------------------------------------------- F-08: revocation fails closed


class _DownCache:
    """Cache stub for an unreachable shared backend.

    Regular ops degrade to an empty cache (the dashboard/RAG caches must
    stay fail-soft); the strict pair raises — the contract every
    impersonation-revocation touch point now relies on.
    """

    def get_json(self, key: str) -> object:
        return None

    def set_json(self, key: str, value: object, ttl: float) -> None:
        return None

    def clear(self) -> None:
        return None

    def ping(self) -> bool:
        return False

    def get_json_strict(self, key: str) -> object:
        raise CacheUnavailable("backend down")

    def set_json_strict(self, key: str, value: object, ttl: float) -> None:
        raise CacheUnavailable("backend down")


def _swap_cache(client: TestClient, stub: _DownCache) -> object:
    """Point the app at the dead backend, return the original for restore."""
    ctx = client.app.state.ctx
    original = ctx.cache
    ctx.cache = stub
    return original


def _impersonation_phases(factory) -> list:
    db = factory()
    try:
        rows = (
            db.execute(select(AuditLog).where(AuditLog.action == "impersonation")).scalars().all()
        )
        return [row.detail.get("phase") for row in rows]
    finally:
        db.close()


def test_impersonation_revoke_fails_closed_when_cache_down(pair) -> None:
    client, factory = pair
    me = _register(client, "s@example.com")
    admin = _admin_headers(client)
    imp_token = _impersonate(client, admin, me["user_id"])
    imp = {"Authorization": f"Bearer {imp_token}"}

    original = _swap_cache(client, _DownCache())
    try:
        res = client.delete(f"/admin/users/{me['user_id']}/impersonate", headers=admin)
        assert res.status_code == 503, res.text
        assert res.json()["detail"]["code"] == "revocation_unavailable"
        # the audit trail must NOT claim a stop that never happened
        assert _impersonation_phases(factory) == ["start"]
    finally:
        client.app.state.ctx.cache = original

    # revocation did not land, so the session is still live — no lie anywhere
    assert client.get("/users/me", headers=imp).status_code == 200


def test_impersonation_start_fails_closed_when_cache_down(pair) -> None:
    client, factory = pair
    me = _register(client, "s@example.com")
    admin = _admin_headers(client)

    original = _swap_cache(client, _DownCache())
    try:
        res = client.post(
            f"/admin/users/{me['user_id']}/impersonate",
            json={"reason": "repro"},
            headers=admin,
        )
        assert res.status_code == 503, res.text
        assert res.json()["detail"]["code"] == "revocation_unavailable"
        # no token was minted into an unrevokable state and nothing was audited
        assert _impersonation_phases(factory) == []
    finally:
        client.app.state.ctx.cache = original


def test_impersonation_exit_fails_closed_when_cache_down(pair) -> None:
    client, factory = pair
    me = _register(client, "s@example.com")
    admin = _admin_headers(client)
    imp_token = _impersonate(client, admin, me["user_id"])
    imp = {"Authorization": f"Bearer {imp_token}"}

    original = _swap_cache(client, _DownCache())
    try:
        res = client.post("/auth/impersonate/exit", headers=imp)
        assert res.status_code == 503, res.text
        assert res.json()["detail"]["code"] == "revocation_unavailable"
        assert _impersonation_phases(factory) == ["start"]
    finally:
        client.app.state.ctx.cache = original

    assert client.get("/users/me", headers=imp).status_code == 200


def test_impersonation_tokens_rejected_while_revocation_store_unreachable(pair) -> None:
    client, _ = pair
    me = _register(client, "s@example.com")
    admin = _admin_headers(client)
    imp_token = _impersonate(client, admin, me["user_id"])
    imp = {"Authorization": f"Bearer {imp_token}"}
    student = _login(client, "s@example.com")

    original = _swap_cache(client, _DownCache())
    try:
        # an impersonation token whose revocation state cannot be checked
        # fails closed instead of silently passing
        assert client.get("/users/me", headers=imp).status_code == 503
        # plain tokens never touch the revocation store — unaffected
        assert client.get("/users/me", headers=student).status_code == 200
    finally:
        client.app.state.ctx.cache = original
