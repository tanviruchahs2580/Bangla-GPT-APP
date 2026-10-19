"""Fault injection at the process boundary (E-15 / I-03).

The audit recorded (AUD-EF-18) that provider faults were well covered --
timeouts, 429/5xx, exhausted retries, blocked candidates, stream errors --
while **nothing injected a dead database or a dead SMTP hop end to end**. This
file closes that gap. Faults are injected where they actually happen in
production, and the dependencies are not mocked away:

* **Database** -- SQLite serves the request flow, then the app's session
  factory is re-bound to an engine whose server refuses connections
  (``127.0.0.1:1``), i.e. the failover case: the process is healthy and the
  store is gone. The assertion is on observable behaviour: ``/ready`` drains
  the worker (503), the public status page flips the database component, and a
  normal request answers the coded, request-id-bearing 500 envelope without
  leaking the DSN -- and without hanging.
* **SMTP** -- a real ``smtplib`` connect to a closed port (no patching at
  all). Delivery must be reported as ``False``, and registration / password
  reset must still complete: a mail relay outage is not an account outage.
* **LLM** -- a real ``GeminiProvider`` on an ``httpx.MockTransport`` that
  fails the way the vendor does (429, connect timeout, non-JSON body), routed
  through ``create_app`` by monkeypatching the documented
  ``bangla_gpt_api.main.get_provider`` seam. The user-visible contract is a
  502 ``llm_unavailable``, never an unhandled 500.

Every test here fails if the corresponding guard is removed: delete the
``except Exception`` in ``/ready``, the ``except ProviderError`` in the ask
route, or the ``except (OSError, smtplib.SMTPException)`` in ``send_mail`` and
the matching test goes red.
"""

from __future__ import annotations

import sqlite3
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import bangla_gpt_api.main as main_module
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.gemini import GeminiProvider
from bangla_gpt_api.services.mailer import send_mail, smtp_configured
from factories import BN, BN_GROUNDED_QUESTION, unique_email

JWT = "test-secret-0123456789abcdef0123456789"
PASSWORD = "Str0ngPassw0rd!"
#: A port nothing listens on. TCP connect to it is refused immediately, which
#: is what "the database/relay is gone" looks like from the client side.
CLOSED_PORT = 1
DEAD_DB_URL = f"postgresql+psycopg://bgpt:bgpt@127.0.0.1:{CLOSED_PORT}/bgpt"

#: A grounded Bangla answer (echoes the corpus sentence) for the control test.
BN_SENTENCE_ANSWER = (
    f"{BN['plant']} {BN['sunlight']} \u0993 {BN['chlorophyll']} "
    "\u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09c7 "
    f"{BN['photosynthesis']} \u0995\u09b0\u09c7{BN['danda']}"
)


def _settings(tmp_path, **over) -> Settings:
    base = dict(
        env="test",
        database_url=f"sqlite:///{tmp_path}/faults.db",
        jwt_secret=JWT,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    base.update(over)
    return Settings(**base)


def _register(client: TestClient, email: str) -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": BN["student"],
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text


def _login(client: TestClient, email: str) -> dict[str, str]:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _kill_database(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Re-bind the app's session factory to a refusing engine (failover)."""
    dead_engine = create_engine(DEAD_DB_URL, connect_args={"connect_timeout": 2})
    monkeypatch.setattr(
        client.app.state.ctx,
        "session_factory",
        sessionmaker(bind=dead_engine, autoflush=False, expire_on_commit=False),
    )
    return dead_engine


# ── database down ─────────────────────────────────────────────────────────


def test_ready_drains_the_worker_when_the_database_disappears(tmp_path, monkeypatch) -> None:
    """Readiness must state the dependency the product needs: the store.

    Mutation that breaks it: removing the ``db.execute(select(1))`` guard (or
    its ``except``) from ``/ready`` -- the worker would keep answering "ready"
    while every student request 500s.
    """
    client = TestClient(create_app(_settings(tmp_path)))
    assert client.get("/ready").status_code == 200

    _kill_database(client, monkeypatch)

    started = time.perf_counter()
    res = client.get("/ready")
    elapsed = time.perf_counter() - started
    assert res.status_code == 503
    assert res.json()["detail"] == "Database unavailable"
    assert elapsed < 10, "readiness must fail fast, not hang on a dead store"


def test_public_status_page_reports_the_database_as_unreachable(tmp_path, monkeypatch) -> None:
    """``/status`` degrades the database component instead of 500ing (no auth)."""
    client = TestClient(create_app(_settings(tmp_path)))
    ok = [c for c in client.get("/status").json()["components"] if c["name"] == "database"]
    assert ok and ok[0]["ok"] is True

    _kill_database(client, monkeypatch)

    res = client.get("/status")
    assert res.status_code == 200
    database = next(c for c in res.json()["components"] if c["name"] == "database")
    assert database["ok"] is False
    assert database["detail"] == "unreachable"


def test_request_during_a_database_outage_is_a_coded_500_with_no_dsn_leak(
    tmp_path, monkeypatch
) -> None:
    """A normal authenticated request against a dead store: coded 500 + headers.

    What is asserted, and why each part matters:

    * 500 (not 401) -- a store outage must not look like a credential problem,
      or every client logs its users out during a failover;
    * ``internal_error`` code inside ``detail`` -- the documented envelope;
    * ``X-Request-ID`` + hardening headers -- the response still went through
      the request-id and security-header middleware;
    * the DSN and the driver's exception text never appear in the body.
    """
    settings = _settings(tmp_path)
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    email = unique_email("outage")
    _register(client, email)
    headers = _login(client, email)
    assert client.get("/users/me", headers=headers).status_code == 200

    _kill_database(client, monkeypatch)

    started = time.perf_counter()
    res = client.get("/users/me", headers=headers)
    elapsed = time.perf_counter() - started
    assert res.status_code == 500
    assert res.json()["detail"]["code"] == "internal_error"
    assert res.headers.get("X-Request-ID")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert "psycopg" not in res.text
    assert "127.0.0.1" not in res.text
    assert elapsed < 15, "a dead store must fail the request, not hang the worker"


def test_tutor_ask_under_a_database_outage_is_coded_and_still_traceable(
    tmp_path, monkeypatch
) -> None:
    """The busiest student route behaves the same way (no route-specific 500)."""
    client = TestClient(create_app(_settings(tmp_path)), raise_server_exceptions=False)
    email = unique_email("outage-ask")
    _register(client, email)
    headers = _login(client, email)

    _kill_database(client, monkeypatch)

    res = client.post(
        "/tutor/ask",
        json={"question": BN["question"], "class_level": 6, "subject": BN["science"]},
        headers=headers,
    )
    assert res.status_code == 500
    assert res.json()["detail"]["code"] == "internal_error"
    assert res.headers.get("X-Request-ID")


# ── SMTP down ─────────────────────────────────────────────────────────────


def _dead_smtp_settings(tmp_path) -> Settings:
    return _settings(
        tmp_path,
        smtp_enabled=True,
        smtp_host="127.0.0.1",
        smtp_port=CLOSED_PORT,
        smtp_from="no-reply@example.test",
    )


def test_send_mail_reports_a_refused_connection_as_false(tmp_path) -> None:
    """The mailer's contract: log and return False, never raise into the caller.

    Mutation that breaks it: dropping ``except (OSError, smtplib.SMTPException)``
    -- the exception then escapes into the request handler.
    """
    settings = _dead_smtp_settings(tmp_path)
    assert smtp_configured(settings) is True

    started = time.perf_counter()
    assert send_mail(settings, to="guardian@example.test", subject="s", body="b") is False
    assert time.perf_counter() - started < 15


def test_registration_completes_while_the_mail_relay_is_down(tmp_path) -> None:
    """A dead relay must not turn account creation into a 500.

    What happens instead is the documented policy, and it is worth pinning:
    with SMTP configured the account is created **unverified**, so sign-in
    answers 403 ``email_unverified`` until the code is entered -- and the
    resend route (the recovery path) still mints a fresh code. The outage
    therefore degrades into a recoverable state, not a half-created account
    and not a 500. The verification row proves the code was minted even
    though no mail left the box.
    """
    db_path = tmp_path / "faults.db"
    client = TestClient(create_app(_dead_smtp_settings(tmp_path)))
    email = unique_email("relay-down")
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": BN["student"],
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text

    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 403
    assert login.json()["detail"]["code"] == "email_unverified"

    # Recovery path: ask for a fresh code; it must not 500 either.
    resend = client.post("/auth/resend-verification", json={"email": email})
    assert resend.status_code in (200, 202), resend.text

    con = sqlite3.connect(db_path)
    try:
        user_id = con.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
        live_codes = con.execute(
            "SELECT COUNT(*) FROM email_verifications WHERE user_id = ? AND used_at IS NULL",
            (user_id,),
        ).fetchone()[0]
    finally:
        con.close()
    assert live_codes == 1, "resend must leave exactly one live code (the old one is burned)"


def test_password_reset_is_accepted_when_the_relay_is_down(tmp_path) -> None:
    """``/auth/forgot`` stays 202 + generic and still mints exactly one token.

    Counting the rows in the database file (the app's own DB, opened with the
    stdlib driver) is a deliberately different method than the response body:
    the flow must complete, not just answer politely.
    """
    db_path = tmp_path / "faults.db"
    client = TestClient(create_app(_dead_smtp_settings(tmp_path)))
    email = unique_email("forgot-down")
    _register(client, email)

    res = client.post("/auth/forgot", json={"email": email})
    assert res.status_code == 202
    assert res.json() == {"status": "accepted"}  # no enumeration signal

    con = sqlite3.connect(db_path)
    try:
        user_id = con.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
        rows = con.execute(
            "SELECT COUNT(*) FROM password_resets WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
    finally:
        con.close()
    assert rows == 1


# ── LLM faults through the HTTP route ─────────────────────────────────────


def _gemini_on(handler) -> GeminiProvider:
    return GeminiProvider(
        api_key="test-key",
        model="gemini-2.5-flash",
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )


def _ask_payload() -> dict:
    # A question the bundled corpus grounds ("## কোষ কী" is a section heading
    # in class6_science.md), so the turn actually reaches the provider instead
    # of being refused at the retrieval gate -- otherwise a provider fault
    # would be untested and the control test would pass for the wrong reason.
    return {"question": BN_GROUNDED_QUESTION, "class_level": 6, "subject": "science"}


def _client_with_provider(tmp_path, provider, monkeypatch) -> TestClient:
    """Build the app with ``provider`` in both lanes (the documented seam)."""
    monkeypatch.setattr(main_module, "get_provider", lambda settings: provider)
    monkeypatch.setattr(main_module, "get_fast_provider", lambda settings: provider)
    settings = _settings(
        tmp_path,
        llm_provider="gemini",
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-flash",
        llm_max_retries=0,
    )
    return TestClient(create_app(settings))


def _gemini_error(status: int, name: str, message: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"code": status, "message": message, "status": name}},
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta"),
    )


def test_route_control_case_grounded_answer_needs_a_working_provider(tmp_path, monkeypatch) -> None:
    """Control: the same request succeeds with a provider that answers.

    Without this, the three fault tests below could pass for the wrong reason
    (an ungrounded question never reaches the provider at all).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": BN_SENTENCE_ANSWER}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ]
            },
            request=request,
        )

    client = _client_with_provider(tmp_path, _gemini_on(handler), monkeypatch)
    email = unique_email("llm-ok")
    _register(client, email)
    res = client.post("/tutor/ask", json=_ask_payload(), headers=_login(client, email))
    assert res.status_code == 200, res.text


@pytest.mark.parametrize(
    "handler, label",
    [
        (
            lambda request: _gemini_error(429, "RESOURCE_EXHAUSTED", "quota exceeded"),
            "429 rate limited",
        ),
        (
            lambda request: (_ for _ in ()).throw(httpx.ConnectTimeout("upstream hang")),
            "connect timeout",
        ),
        (
            lambda request: httpx.Response(
                200,
                content=b"<html>gateway error</html>",
                headers={"content-type": "application/json"},
                request=request,
            ),
            "malformed (non-JSON) body",
        ),
    ],
    ids=["429", "timeout", "malformed"],
)
def test_llm_faults_map_to_a_coded_502(tmp_path, monkeypatch, handler, label: str) -> None:
    """429 / timeout / malformed upstream body: 502 ``llm_unavailable``.

    Raw provider faults are turned into a controlled status by the ask route;
    mutation that breaks it: removing the ``except ProviderError`` block in
    ``routers/tutor.py`` (the response becomes an unhandled 500) or letting the
    provider re-raise httpx's own exception type.
    """
    client = _client_with_provider(tmp_path, _gemini_on(handler), monkeypatch)
    email = unique_email("llm-fault")
    _register(client, email)
    res = client.post("/tutor/ask", json=_ask_payload(), headers=_login(client, email))
    if res.status_code == 500:  # pragma: no cover - failure diagnostics
        raise AssertionError(f"{label}: leaked as a 500: {res.text}")
    assert res.status_code == 502, f"{label}: {res.status_code} {res.text}"
    assert res.json()["detail"]["code"] == "llm_unavailable"
    assert "quota" not in res.text and "gateway error" not in res.text
