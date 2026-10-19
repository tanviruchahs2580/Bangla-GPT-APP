"""AUD-B-29 verification: run the retention purge on SEEDED OLD data.

The B register lists B-29 as PASS on the strength of the existing suite; this
is an independent re-execution with explicit old/new pairs so the claim
"purges what policy says, keeps what it does not" is observed, not inferred:

* a conversation 200 days old (retention default 180) with messages, plus a
  fresh one -- old gone, fresh kept;
* password-reset / email-verification rows expired beyond the 30-day token
  grace, plus fresh ones -- old gone, fresh kept;
* a USED parent invite expired beyond the grace (removed) and an UNUSED one
  (kept: it may still be redeemed or expire naturally);
* analytics events older than the retention window (F-058: documented but
  never swept before) and fresh ones;
* dry-run performs NO deletes and returns the same counts the real run reports;
* the admin endpoint writes exactly one counts-only `purge` audit row.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    AnalyticsEventRow,
    ChatMessage,
    Conversation,
    EmailVerification,
    ParentInvite,
    PasswordReset,
    Student,
    User,
)
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.retention import run_retention_sweep

SECRET = "test-secret-0123456789abcdef0123456789"
ADMIN_PASSWORD = "Adm1n-Str0ng-Passphrase!"
RETENTION_DAYS = 180


def _settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/retention.db",
        jwt_secret=SECRET,
        admin_email="root@example.test",
        admin_password=ADMIN_PASSWORD,
        force_admin_password_change=False,
        chat_retention_days=RETENTION_DAYS,
    )


def _seed(settings: Settings) -> dict[str, int]:
    """Old/new pairs for every row class the sweep owns. Returns ids."""
    factory = make_session_factory(make_engine(settings))
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    old = now - dt.timedelta(days=RETENTION_DAYS + 20)
    fresh = now - dt.timedelta(days=5)
    ids: dict[str, int] = {}
    with factory() as db:
        user = User(email="student@example.test", password_hash="x", role="student")
        db.add(user)
        db.flush()
        student = Student(user_id=user.id, name="S", class_level=6)
        db.add(student)
        db.flush()

        def conversation(created: dt.datetime) -> Conversation:
            convo = Conversation(student_id=student.id, title="t")
            db.add(convo)
            db.flush()
            db.add(ChatMessage(conversation_id=convo.id, role="user", content="hi"))
            db.flush()
            # created_at is default-only; pin it explicitly for the sweep.
            convo.created_at = created
            return convo

        old_convo = conversation(old)
        fresh_convo = conversation(fresh)
        ids["old_convo"] = old_convo.id
        ids["fresh_convo"] = fresh_convo.id

        for label, expires in (
            ("old_reset", now - dt.timedelta(days=45)),
            ("fresh_reset", now - dt.timedelta(days=1)),
        ):
            row = PasswordReset(
                user_id=user.id, token_hash=label.ljust(64, "0"), expires_at=expires
            )
            db.add(row)
            db.flush()
            ids[label] = row.id
        for label, expires in (
            ("old_verification", now - dt.timedelta(days=45)),
            ("fresh_verification", now - dt.timedelta(days=1)),
        ):
            row = EmailVerification(
                user_id=user.id, token_hash=label.ljust(64, "1"), expires_at=expires
            )
            db.add(row)
            db.flush()
            ids[label] = row.id
        used_invite = ParentInvite(
            code_hash="a" * 64,
            student_id=student.id,
            expires_at=now - dt.timedelta(days=45),
            used_at=now - dt.timedelta(days=60),
        )
        unused_invite = ParentInvite(
            code_hash="b" * 64,
            student_id=student.id,
            expires_at=now + dt.timedelta(days=5),
        )
        db.add_all([used_invite, unused_invite])
        db.flush()
        ids["used_invite"] = used_invite.id
        ids["unused_invite"] = unused_invite.id

        for label, created in (("old_event", old), ("fresh_event", fresh)):
            row = AnalyticsEventRow(user_id=user.id, name="view", props={})
            db.add(row)
            db.flush()
            row.created_at = created
            ids[label] = row.id
        db.commit()
    return ids


@pytest.fixture()
def app_ctx_factory(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    ids = _seed(settings)
    return app, settings, ids


def _count(settings: Settings, model: type, row_id: int) -> bool:
    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        return db.get(model, row_id) is not None


def test_dry_run_reports_without_deleting(app_ctx_factory) -> None:
    _, settings, ids = app_ctx_factory
    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        report = run_retention_sweep(db, settings=settings, dry_run=True)
    assert report["dry_run"] is True
    assert report["conversations_deleted"] == 1
    assert report["chat_messages_deleted"] == 1
    assert report["password_resets_deleted"] == 1
    assert report["email_verifications_deleted"] == 1
    assert report["used_invites_deleted"] == 1
    assert report["analytics_events_deleted"] == 1
    # Nothing was actually removed.
    assert _count(settings, Conversation, ids["old_convo"]) is True
    assert _count(settings, PasswordReset, ids["old_reset"]) is True


def test_real_sweep_removes_old_and_keeps_fresh(app_ctx_factory) -> None:
    _, settings, ids = app_ctx_factory
    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        report = run_retention_sweep(db, settings=settings, dry_run=False)
        # The service participates in the caller's transaction (the endpoint
        # commits after writing the audit row); commit here to persist.
        db.commit()
    assert report["dry_run"] is False
    assert report["conversations_deleted"] == 1

    # Old rows of every class are gone...
    assert _count(settings, Conversation, ids["old_convo"]) is False
    assert _count(settings, PasswordReset, ids["old_reset"]) is False
    assert _count(settings, EmailVerification, ids["old_verification"]) is False
    assert _count(settings, ParentInvite, ids["used_invite"]) is False
    assert _count(settings, AnalyticsEventRow, ids["old_event"]) is False
    # ...fresh rows and the unused invite survive.
    assert _count(settings, Conversation, ids["fresh_convo"]) is True
    assert _count(settings, PasswordReset, ids["fresh_reset"]) is True
    assert _count(settings, EmailVerification, ids["fresh_verification"]) is True
    assert _count(settings, ParentInvite, ids["unused_invite"]) is True
    assert _count(settings, AnalyticsEventRow, ids["fresh_event"]) is True


def test_admin_endpoint_runs_the_sweep_and_audits_counts_only(app_ctx_factory) -> None:
    app, settings, ids = app_ctx_factory
    client = TestClient(app)
    login = client.post(
        "/auth/login", json={"email": "root@example.test", "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200, login.text
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    dry = client.post("/admin/maintenance/purge", params={"dry_run": True})
    assert dry.status_code == 200, dry.text
    assert dry.json()["dry_run"] is True
    assert _count(settings, Conversation, ids["old_convo"]) is True

    real = client.post("/admin/maintenance/purge")
    assert real.status_code == 200, real.text
    assert real.json()["conversations_deleted"] == 1

    audit = client.get("/admin/audit", params={"action": "purge"})
    assert audit.status_code == 200, audit.text
    rows = audit.json()["rows"]
    assert len(rows) == 1
    detail = rows[0]["detail"]
    assert detail["conversations_deleted"] == 1
    # Counts only: no content, no list payloads.
    assert all(isinstance(value, int) for value in detail.values())
