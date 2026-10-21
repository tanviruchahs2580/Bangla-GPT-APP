"""H-11 / AUD-HI-17: the email surface -- sandbox delivery, bounce path, preferences.

Three gaps the audit found, pinned here end to end:

1. **Sandbox delivery** -- Mailpit is not available, so the test starts the
   local fake SMTP server from ``tests/fake_smtp.py`` (stdlib + cryptography,
   real STARTTLS with a temporary CA, real AUTH PLAIN) and drives
   ``mailer.send_mail`` -- the production path, not a re-implementation.
2. **Bounce handling** -- an RFC 3464 DSN and a provider-style
   ``X-Failed-Recipients`` message are parsed, ingested into the suppression
   ledger, and a suppressed guardian stops receiving the bulk digest while
   transactional mail stays unaffected.
3. **Preferences and languages** -- ``parents.digest_opt_out`` skips a
   guardian (counted), ``parents.digest_language`` selects the bn or en
   template, an unknown language falls back to bn, and no subject carries PII
   (the recipient's email/name never appears in it).
"""

from __future__ import annotations

import sqlite3
import ssl
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bangla_gpt_api.config import Settings  # noqa: E402
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory  # noqa: E402
from bangla_gpt_api.services import mailer  # noqa: E402
from bangla_gpt_api.services.parent_digest import build_body, run_weekly_digest  # noqa: E402
from fake_smtp import FakeIMAP, FakeSMTPServer  # noqa: E402

# "রহিম" -- an ordinary Bangla name, in the house escape style (NFC form:
# the ya+nukta is U+09AF U+09BC, never the precomposed U+09DF).
RAHIM = "রহিম"

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
GUARDIAN = "guardian@example.com"
GUARDIAN_BN = "guardian-bn@example.com"
GUARDIAN_EN = "guardian-en@example.com"
GUARDIAN_OFF = "guardian-off@example.com"

# RFC 3464 multipart/report: hard bounce for GUARDIAN.
DSN_HARD = f"""From: MAILER-DAEMON@relay.example
To: bounce@bgpt.test
Subject: Undelivered Mail Returned to Sender
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="B"

--B
Content-Type: text/plain

Delivery to the following recipient failed permanently.
--B
Content-Type: message/delivery-status

Reporting-MTA: dns; relay.example

Final-Recipient: rfc822; {GUARDIAN}
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550 5.1.1 User unknown
--B--
"""

# A delayed (soft) report must NOT suppress anybody.
DSN_SOFT = f"""From: MAILER-DAEMON@relay.example
To: bounce@bgpt.test
Subject: Delayed delivery
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="C"

--C
Content-Type: text/plain

Delivery is delayed.
--C
Content-Type: message/delivery-status

Reporting-MTA: dns; relay.example

Final-Recipient: rfc822; {GUARDIAN_BN}
Action: delayed
Status: 4.4.1
Diagnostic-Code: smtp; 451 4.4.1 try again
--C--
"""

# Provider-style bounce: no DSN part, just the failed-recipient header.
PROVIDER_BOUNCE = f"""From: postmaster@relay.example
To: bounce@bgpt.test
Subject: Delivery Status Notification (Failure)
X-Failed-Recipients: {GUARDIAN_EN}

This is an automatically generated message.
"""


def _settings(db_path: Path, server: FakeSMTPServer | None) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{db_path}",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
        smtp_enabled=server is not None,
        smtp_host=server.host if server else None,
        smtp_port=server.port if server else 587,
        smtp_user="relay" if server else None,
        smtp_password="secret" if server else None,
        smtp_from="noreply@bgpt.test" if server else None,
    )


@pytest.fixture
def trust_fake_ca(monkeypatch):
    """Make ``ssl.create_default_context()`` trust the fake server's CA.

    The seam is the trust anchor only: certificate and hostname verification
    stay ON. (``SSL_CERT_FILE`` is not enough -- on Windows Python loads the
    system certificate store instead of the OpenSSL default paths, so the test
    would pass on Linux CI and fail locally.)
    """
    real = ssl.create_default_context
    return lambda cafile: monkeypatch.setattr(
        ssl, "create_default_context", lambda: real(cafile=cafile)
    )


# ── 1. sandbox delivery through the production send path ──────────────


def test_send_mail_through_local_smtp_sandbox(tmp_path, monkeypatch, trust_fake_ca) -> None:
    with FakeSMTPServer(require_auth=True, username="relay", password="secret") as server:
        trust_fake_ca(server.ca_file)
        settings = _settings(tmp_path / "sandbox.db", server)
        # "প্রিয় অভিভাবক" -- greeting with the decomposed ya+nukta form (NFC).
        greeting = "\u09aa\u09cd\u09b0\u09bf\u09af\u09bc \u0985\u09ad\u09bf\u09ad\u09be\u09ac\u0995"
        assert mailer.send_mail(
            settings, to=GUARDIAN_BN, subject="Weekly parent digest", body=greeting
        )
        assert len(server.messages) == 1
        captured = server.messages[0]
        assert captured.to == GUARDIAN_BN
        assert captured.sender == "noreply@bgpt.test"
        assert captured.subject == "Weekly parent digest"
        # Bangla survives the SMTP DATA round trip byte-for-byte.
        assert greeting in captured.body
        assert captured.body == greeting


def test_send_mail_returns_false_on_recipient_rejection(tmp_path, trust_fake_ca) -> None:
    with FakeSMTPServer(
        require_auth=True, username="relay", password="secret", reject_recipients=(GUARDIAN,)
    ) as server:
        trust_fake_ca(server.ca_file)
        settings = _settings(tmp_path / "reject.db", server)
        assert mailer.send_mail(settings, to=GUARDIAN, subject="s", body="b") is False
        assert server.messages == []


def test_send_mail_without_configuration_is_false(tmp_path) -> None:
    settings = _settings(tmp_path / "nocfg.db", None)
    assert mailer.send_mail(settings, to=GUARDIAN, subject="s", body="b") is False
    assert mailer.smtp_configured(settings) is False


# ── 2. bounce parsing and suppression ─────────────────────────────────


def test_parse_hard_dsn_and_provider_bounce() -> None:
    hard = mailer.parse_bounce_message(DSN_HARD)
    assert [(b.address, b.action, b.status) for b in hard] == [(GUARDIAN, "failed", "5.1.1")]
    assert hard[0].is_hard
    assert "550 5.1.1 User unknown" in hard[0].diagnostic
    soft = mailer.parse_bounce_message(DSN_SOFT)
    assert soft and soft[0].address == GUARDIAN_BN and not soft[0].is_hard
    provider = mailer.parse_bounce_message(PROVIDER_BOUNCE)
    assert [b.address for b in provider] == [GUARDIAN_EN]


def test_ingest_records_only_hard_bounces(tmp_path) -> None:
    db_path = tmp_path / "bounces.db"
    engine = make_engine(_settings(db_path, None))
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        assert mailer.ingest_bounce_message(db, DSN_HARD) == [GUARDIAN]
        assert mailer.ingest_bounce_message(db, DSN_SOFT) == []
        assert mailer.ingest_bounce_message(db, PROVIDER_BOUNCE) == [GUARDIAN_EN]
        assert mailer.is_suppressed(db, GUARDIAN) is True
        assert mailer.is_suppressed(db, GUARDIAN.upper()) is True  # case-insensitive
        assert mailer.is_suppressed(db, GUARDIAN_BN) is False
        # A second DSN for the same recipient re-stamps, never duplicates.
        mailer.ingest_bounce_message(db, DSN_HARD)
        from bangla_gpt_api.db.models import EmailBounce

        rows = db.query(EmailBounce).all()
        assert len(rows) == 2
        stamped = next(r for r in rows if r.recipient_hash == mailer.recipient_hash(GUARDIAN))
        assert stamped.bounce_count == 2
        # The ledger stores a hash, never the address itself.
        assert GUARDIAN not in "".join(str(r.recipient_hash) for r in rows)


def test_send_mail_checked_refuses_suppressed_recipient(tmp_path, trust_fake_ca) -> None:
    with FakeSMTPServer(require_auth=True, username="relay", password="secret") as server:
        trust_fake_ca(server.ca_file)
        db_path = tmp_path / "supp.db"
        settings = _settings(db_path, server)
        engine = make_engine(settings)
        init_db(engine)
        factory = make_session_factory(engine)
        with factory() as db:
            assert mailer.send_mail_checked(db, settings, to=GUARDIAN, subject="s", body="b")
            mailer.ingest_bounce_message(db, DSN_HARD)
            assert not mailer.send_mail_checked(db, settings, to=GUARDIAN, subject="s", body="b")
        assert len(server.messages) == 1  # only the pre-bounce send arrived


def test_ingest_bounces_via_imap_with_fake_server(tmp_path) -> None:
    db_path = tmp_path / "imap.db"
    engine = make_engine(_settings(db_path, None))
    init_db(engine)
    factory = make_session_factory(engine)
    imap = FakeIMAP(script={"1": [DSN_HARD.encode()], "2": [PROVIDER_BOUNCE.encode()]})
    with factory() as db:
        recorded = mailer.ingest_bounces_via_imap(
            db,
            host="imap.example",
            user="bounces",
            password="secret",
            server_factory=lambda: imap,
        )
    assert sorted(recorded) == sorted([GUARDIAN, GUARDIAN_EN])
    assert imap.selected == "INBOX"
    assert sorted(imap.seen) == ["1", "2"]


# ── 3. preferences, languages and the digest end to end ───────────────


def _seed_family(db_path: Path, *, email: str, name: str, opt_out: bool, language: str) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, 'x', 'parent', ?)",
            (email, str(now)),
        )
        user_id = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
        conn.execute(
            "INSERT INTO parents (user_id, name, digest_opt_out, digest_language, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, name, int(opt_out), language, str(now)),
        )
        parent_id = conn.execute("SELECT id FROM parents WHERE user_id=?", (user_id,)).fetchone()[0]
        student_email = f"kid-{email}"
        conn.execute(
            "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, 'x', 'student', ?)",
            (student_email, str(now)),
        )
        student_user = conn.execute(
            "SELECT id FROM users WHERE email=?", (student_email,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO students (user_id, name, class_level, consent_version, consent_at,"
            " created_at) VALUES (?, ?, 6, 'T-1', ?, ?)",
            (student_user, RAHIM, str(now), str(now)),
        )
        student_id = conn.execute(
            "SELECT id FROM students WHERE user_id=?", (student_user,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO parent_student_links (parent_id, student_id, created_at) VALUES (?, ?, ?)",
            (parent_id, student_id, str(now)),
        )
        conn.execute(
            "INSERT INTO conversations (student_id, title, last_strategy, created_at)"
            " VALUES (?, 'Algebra help', NULL, ?)",
            (student_id, str(now - timedelta(hours=3))),
        )
        conn.execute(
            "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total, correct,"
            " score_pct, quiz_json, created_at) VALUES (?, 'math', 6, 'graded', 4, 3, 75.0, '[]', ?)",
            (student_id, str(now - timedelta(hours=2))),
        )
        conn.commit()
    finally:
        conn.close()


def test_digest_honours_preferences_languages_and_suppression(tmp_path, trust_fake_ca) -> None:
    with FakeSMTPServer(require_auth=True, username="relay", password="secret") as server:
        trust_fake_ca(server.ca_file)
        db_path = tmp_path / "digest.db"
        settings = _settings(db_path, server)
        engine = make_engine(settings)
        init_db(engine)
        _seed_family(db_path, email=GUARDIAN_BN, name="Ayesha", opt_out=False, language="bn")
        _seed_family(db_path, email=GUARDIAN_EN, name="Karim", opt_out=False, language="en")
        _seed_family(db_path, email=GUARDIAN_OFF, name="Nasrin", opt_out=True, language="en")
        _seed_family(
            db_path,
            email=GUARDIAN,  # will be suppressed *before* the run
            name="Rahima",
            opt_out=False,
            language="bn",
        )
        factory = make_session_factory(engine)
        with factory() as db:
            mailer.ingest_bounce_message(db, DSN_HARD)
            stats = run_weekly_digest(settings, db, now=datetime.now(UTC).replace(tzinfo=None))
        assert stats.families == 3  # the opted-out guardian never reaches the send
        assert stats.opted_out == 1
        assert stats.delivered == 2
        assert stats.undelivered == 1  # the suppressed guardian
        assert len(server.messages) == 2  # exactly the two deliveries
        by_to = {m.to: m for m in server.messages}
        assert set(by_to) == {GUARDIAN_BN, GUARDIAN_EN}
        bn, en = by_to[GUARDIAN_BN], by_to[GUARDIAN_EN]
        assert (
            "Weekly parent digest" in bn.subject
            and "\u09b8\u09be\u09aa\u09cd\u09a4\u09be\u09b9\u09bf\u0995" in bn.subject
        )
        assert en.subject == "Weekly parent digest"
        assert "\u09b6\u09cd\u09b0\u09c7\u09a3\u09bf 6" in bn.body  # "শ্রেণি 6"
        assert "Class 6" in en.body and "on track" in en.body
        # No PII in any subject line.
        for message in server.messages:
            assert GUARDIAN_BN not in message.subject
            assert GUARDIAN_EN not in message.subject
            assert "Ayesha" not in message.subject and "Karim" not in message.subject


def test_digest_language_falls_back_to_bengali_for_unknown_value() -> None:
    assert mailer.normalize_language("en") == "en"
    assert mailer.normalize_language("BN") == "bn"
    assert mailer.normalize_language("fr") == "bn"
    assert mailer.normalize_language(None) == "bn"
    assert mailer.normalize_language("") == "bn"


def test_transactional_templates_cover_bn_and_en() -> None:
    for name in ("password_reset", "email_verification"):
        bn_subject, bn_body = mailer.render(name, "bn", minutes=30, token="TOK")
        en_subject, en_body = mailer.render(name, "en", minutes=30, token="TOK")
        assert bn_subject and en_subject and bn_subject != en_subject
        assert "TOK" in bn_body and "TOK" in en_body and "30" in bn_body and "30" in en_body
        # The unknown-language path must not leak a KeyError to a caller.
        assert mailer.render(name, "de", minutes=30, token="TOK")[0] == bn_subject


def test_digest_body_builder_defaults_to_bengali() -> None:
    from bangla_gpt_api.services.parent_digest import ChildSummary, WeeklyDigest

    digest = WeeklyDigest(
        parent_name="Ayesha",
        week_label="01 Jun \u2013 07 Jun",
        children=[ChildSummary(RAHIM, 6, 2, 1, 75.0, False, [])],
    )
    assert "\u09b6\u09cd\u09b0\u09c7\u09a3\u09bf 6" in build_body(digest)
    assert "Class 6" in build_body(digest, "en")
