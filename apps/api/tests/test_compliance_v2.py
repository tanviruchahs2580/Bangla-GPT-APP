"""S5.8 compliance tests.

Two PASS-WHEN halves:
* retention sweep -- dry-run report counts without deleting (compliance
  evidence), real sweep deletes only expired rows + writes the R11-safe
  audit row, and the nightly arq job wrapper claims once per day;
* consent re-confirm flow -- CONSENT_VERSION bump makes GET report
  needs_reconfirm=true, POST re-confirm refreshes the evidence trail.

New file kept ASCII-only (repo rule for new files).
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bangla_gpt_api import jobs
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    AuditLog,
    ChatMessage,
    Conversation,
    EmailVerification,
    ParentInvite,
    PasswordReset,
    Student,
    User,
)
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import CONSENT_VERSION, create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
PREVIOUS_VERSION = "2026-08-v1"  # the version in force before the S5.8 bump
COUNT_KEYS = {
    "conversations_deleted",
    "chat_messages_deleted",
    "password_resets_deleted",
    "email_verifications_deleted",
    "used_invites_deleted",
}


@pytest.fixture
def pair(tmp_path):
    """Client + session factory over the SAME sqlite file (seed/assert directly)."""
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/compliance.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    factory = make_session_factory(make_engine(settings))
    return client, factory, settings


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


def _student_id(client: TestClient, headers: dict) -> int:
    me = client.get("/users/me", headers=headers)
    assert me.status_code == 200
    return me.json()["profile_id"]


def _seed_expired(factory) -> int:
    """One expired set + one fresh conversation that must survive the sweep."""
    now = datetime.now(UTC).replace(tzinfo=None)
    db = factory()
    try:
        student = db.execute(select(Student)).scalar_one()
        user = db.get(User, student.user_id)
        old_conv = Conversation(student_id=student.id, created_at=now - timedelta(days=400))
        fresh_conv = Conversation(student_id=student.id, created_at=now)
        db.add_all([old_conv, fresh_conv])
        db.flush()
        db.add_all(
            [
                ChatMessage(
                    conversation_id=old_conv.id,
                    role="user",
                    content="old question",
                    created_at=now - timedelta(days=400),
                ),
                ChatMessage(
                    conversation_id=fresh_conv.id,
                    role="user",
                    content="recent question",
                    created_at=now,
                ),
                PasswordReset(
                    user_id=user.id, token_hash="a" * 64, expires_at=now - timedelta(days=45)
                ),
                EmailVerification(
                    user_id=user.id, token_hash="b" * 64, expires_at=now - timedelta(days=45)
                ),
                ParentInvite(
                    code_hash="c" * 64,
                    student_id=student.id,
                    expires_at=now - timedelta(days=45),
                    used_at=now - timedelta(days=44),
                ),
            ]
        )
        db.commit()
        return old_conv.id
    finally:
        db.close()


def _row_counts(factory) -> dict[str, int]:
    db = factory()
    try:
        return {
            "conversations": int(db.execute(select(func.count(Conversation.id))).scalar_one()),
            "messages": int(db.execute(select(func.count(ChatMessage.id))).scalar_one()),
            "resets": int(db.execute(select(func.count(PasswordReset.id))).scalar_one()),
            "verifications": int(db.execute(select(func.count(EmailVerification.id))).scalar_one()),
            "invites": int(db.execute(select(func.count(ParentInvite.id))).scalar_one()),
            "purge_audit": int(
                db.execute(
                    select(func.count(AuditLog.id)).where(AuditLog.action == "purge")
                ).scalar_one()
            ),
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Retention sweep: dry-run report / real sweep + audit / nightly job ledger
# ---------------------------------------------------------------------------


def test_retention_dry_run_reports_counts_without_deleting(pair) -> None:
    client, factory, _ = pair
    _register(client, "s58dr@example.com")
    _seed_expired(factory)
    before = _row_counts(factory)
    assert before["conversations"] == 2  # 1 old + 1 fresh

    res = client.post("/admin/maintenance/purge?dry_run=true", headers=_admin_headers(client))
    assert res.status_code == 200
    body = res.json()
    assert body["dry_run"] is True
    assert COUNT_KEYS <= set(body)
    assert body["conversations_deleted"] == 1
    assert body["chat_messages_deleted"] == 1
    assert body["password_resets_deleted"] == 1
    assert body["email_verifications_deleted"] == 1
    assert body["used_invites_deleted"] == 1

    # The report touched NOTHING and left no audit trail.
    assert _row_counts(factory) == before


def test_retention_real_sweep_deletes_expired_and_audits_counts_only(pair) -> None:
    client, factory, _ = pair
    _register(client, "s58real@example.com")
    old_conv_id = _seed_expired(factory)

    res = client.post("/admin/maintenance/purge", headers=_admin_headers(client))
    assert res.status_code == 200
    body = res.json()
    assert body["dry_run"] is False
    assert body["conversations_deleted"] == 1
    assert body["used_invites_deleted"] == 1

    after = _row_counts(factory)
    # Only the expired rows die; the fresh conversation + its message survive.
    assert after["conversations"] == 1
    assert after["messages"] == 1
    assert after["resets"] == 0
    assert after["verifications"] == 0
    assert after["invites"] == 0
    assert after["purge_audit"] == 1

    db = factory()
    try:
        surviving = db.get(Conversation, old_conv_id)
        assert surviving is None
        audit = db.execute(select(AuditLog).where(AuditLog.action == "purge")).scalar_one()
        assert audit.target == "retention_sweep"
        assert audit.actor_role == "admin"
        # R11: counts in detail, never content; the dry_run flag is not data.
        assert COUNT_KEYS <= set(audit.detail)
        assert "dry_run" not in audit.detail
        assert all(isinstance(v, int) for v in audit.detail.values())
    finally:
        db.close()


def test_retention_requires_admin(pair) -> None:
    client, _, _ = pair
    _register(client, "s58plain@example.com")
    headers = _login(client, "s58plain@example.com")
    res = client.post("/admin/maintenance/purge?dry_run=true", headers=headers)
    assert res.status_code == 403


def test_nightly_retention_job_runs_once_per_day(pair) -> None:
    client, factory, settings = pair
    _register(client, "s58job@example.com")
    _seed_expired(factory)

    now = datetime(2026, 9, 6, 3, 0)  # naive UTC, matches the ledger day key
    first = jobs.run_retention_job(factory, settings, now=now)
    assert first["ran"] is True
    assert first["period"] == "2026-09-06"
    assert first["conversations_deleted"] == 1
    assert first["dry_run"] is False
    assert _row_counts(factory)["resets"] == 0  # sweep actually executed

    again = jobs.run_retention_job(factory, settings, now=now)
    assert again == {"ran": False, "reason": "already_ran", "period": "2026-09-06"}

    next_day = jobs.run_retention_job(factory, settings, now=now + timedelta(days=1))
    assert next_day["ran"] is True
    assert next_day["conversations_deleted"] == 0  # idempotent: nothing left


# ---------------------------------------------------------------------------
# Consent re-confirm flow (CONSENT_VERSION bump)
# ---------------------------------------------------------------------------


def test_consent_version_bumped_and_current_after_registration(pair) -> None:
    client, _, _ = pair
    assert CONSENT_VERSION == "2026-09-v2"  # the S5.8 bump itself
    _register(client, "s58ok@example.com")
    headers = _login(client, "s58ok@example.com")
    sid = _student_id(client, headers)

    res = client.get(f"/students/{sid}/consent", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["current_version"] == CONSENT_VERSION
    assert body["accepted_version"] == CONSENT_VERSION
    assert body["needs_reconfirm"] is False  # fresh signup accepted current text


def test_consent_bump_flow_requires_reconfirm_and_refreshes_evidence(pair) -> None:
    client, factory, _ = pair
    _register(client, "s58bump@example.com")
    headers = _login(client, "s58bump@example.com")
    sid = _student_id(client, headers)

    # Simulate the bump: this student only ever accepted the PREVIOUS text.
    db = factory()
    try:
        student = db.get(Student, sid)
        student.consent_version = PREVIOUS_VERSION
        db.commit()
    finally:
        db.close()

    status = client.get(f"/students/{sid}/consent", headers=headers).json()
    assert status["needs_reconfirm"] is True
    assert status["accepted_version"] == PREVIOUS_VERSION

    refused = client.post(
        f"/students/{sid}/consent/reconfirm", json={"accepted": False}, headers=headers
    )
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "consent_not_accepted"
    assert client.get(f"/students/{sid}/consent", headers=headers).json()["needs_reconfirm"]

    accepted = client.post(
        f"/students/{sid}/consent/reconfirm", json={"accepted": True}, headers=headers
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["needs_reconfirm"] is False
    assert body["accepted_version"] == CONSENT_VERSION

    db = factory()
    try:
        student = db.get(Student, sid)
        assert student.consent_version == CONSENT_VERSION
        assert student.consent_at is not None
        assert student.consent_ip  # legal evidence trail refreshed (justified S5.8 review)
    finally:
        db.close()


def test_consent_endpoints_enforce_access(pair) -> None:
    client, _, _ = pair
    _register(client, "s58owner@example.com")
    _register(client, "s58other@example.com")
    _register(client, "s58parent@example.com", role="parent")
    owner_headers = _login(client, "s58owner@example.com")
    sid = _student_id(client, owner_headers)

    other_headers = _login(client, "s58other@example.com")
    assert client.get(f"/students/{sid}/consent", headers=other_headers).status_code == 403
    assert (
        client.post(
            f"/students/{sid}/consent/reconfirm", json={"accepted": True}, headers=other_headers
        ).status_code
        == 403
    )
    parent_headers = _login(client, "s58parent@example.com")
    assert client.get(f"/students/{sid}/consent", headers=parent_headers).status_code == 403
    assert client.get(f"/students/{sid}/consent").status_code == 401
