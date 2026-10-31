"""SEC-08 execution: injection probes run against the real app and renderers.

The audit could only infer these; each probe here executes a hostile input and
pins the observable safety property, not an implementation detail:

* SQL metacharacters in query parameters and JSON fields must not surface a
  database error, and LIKE wildcards must match literally;
* no CSV cell this application delivers may begin with a formula lead;
* a raw control character in X-Request-ID must not survive into the echoed
  response header (the request is driven through the ASGI interface directly,
  bypassing client-side header validation, because that is how a hostile
  proxy or raw TCP client reaches the middleware);
* a newline inside a logged value cannot forge a second log line;
* no export renderer evaluates template syntax contained in user data.
"""

import asyncio
import io
import logging
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from bangla_gpt_api.config import Settings
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services import govt_report
from bangla_gpt_api.services.qp_pdf import render_qp_html, render_qp_pdf
from conftest import engine_url

PASSWORD = "supersecret1"
ADMIN_EMAIL = "root@example.com"

#: Classic tautology/union/comment payloads. None of them is expected to
#: change a response code: they are probes for accidental string splicing.
SQLI_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    "1' UNION SELECT password_hash FROM users --",
    "%' AND 1=1 --",
    '") OR ("1"="1',
    "admin'--",
]

#: Markers that would only appear if a database error reached the client.
_LEAK_MARKERS = (
    "Traceback",
    "sqlalchemy",
    "SQLAlchemy",
    "OperationalError",
    "syntax error",
    "unrecognized token",
    "sqlite3",
)


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2sec08"),
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email=ADMIN_EMAIL,
        admin_password=PASSWORD,
        force_admin_password_change=False,
        **overrides,
    )
    return TestClient(create_app(settings))


def _login_headers(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _register_student(client: TestClient, email: str) -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text


@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_login_sqli_payloads_are_rejected_without_leak(tmp_path, payload: str) -> None:
    client = make_client(tmp_path)
    res = client.post("/auth/login", json={"email": payload, "password": payload})
    assert res.status_code in (401, 422), res.text
    body = res.text
    for marker in _LEAK_MARKERS:
        assert marker not in body, f"{marker!r} leaked for payload {payload!r}"


@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_message_search_sqli_payloads_execute_cleanly(tmp_path, payload: str) -> None:
    """The message search is a real ILIKE; hostile input must return a list."""
    client = make_client(tmp_path)
    email = f"sqli{SQLI_PAYLOADS.index(payload)}@example.com"
    _register_student(client, email)
    headers = _login_headers(client, email)

    # min_length=2: pad single-character payloads so they reach the query.
    query = payload if len(payload) >= 2 else payload * 2
    res = client.get("/tutor/messages/search", params={"q": query}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json() == []
    for marker in _LEAK_MARKERS:
        assert marker not in res.text


@pytest.mark.parametrize("payload", ["%", "_", "%%", r"\%"])
def test_like_wildcards_in_admin_search_match_literally(tmp_path, payload: str) -> None:
    """A lone wildcard must not select every account (F-062 hardening)."""
    client = make_client(tmp_path)
    headers = _login_headers(client, ADMIN_EMAIL)
    res = client.get("/admin/users", params={"q": payload}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["items"] == [], f"{payload!r} matched rows it must not"


@pytest.mark.parametrize("lead", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_cell_escapes_every_formula_lead(lead: str) -> None:
    cell = govt_report._csv_cell(f"{lead}CMD|' /C calc'!A0")
    assert cell.startswith("'"), f"formula lead {lead!r} was not escaped"


def test_aggregate_csv_delivers_no_formula_leads(tmp_path) -> None:
    """End-to-end: the one CSV this API delivers is fetched with a hostile label."""
    client = make_client(tmp_path)
    headers = _login_headers(client, ADMIN_EMAIL)
    res = client.get(
        "/admin/reports/aggregate",
        params={"format": "csv", "district": '=HYPERLINK("http://evil.example")'},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    text = res.content.decode("utf-8-sig")
    for line in text.splitlines():
        assert not line.startswith(("=", "+", "-", "@", "\t", "\r")), line


def test_to_csv_escapes_label_in_delivered_rows() -> None:
    """Unit-level: a row carrying the requester label is escaped by the writer."""
    export = govt_report.AggregateExport(
        meta=govt_report.AggregateMeta(
            generated_at="2026-10-29T00:00:00Z",
            district_tag='=HYPERLINK("http://evil.example")',
            since_days=None,
            min_cell=5,
            suppressed_cells=0,
            total_students_included=10,
        ),
        rows=[
            {
                "class_level": 6,
                "subject": "science",
                "students": 10,
                "quiz_attempts": 12,
                "avg_score_pct": 61.0,
                "active_tutor_students": 4,
            }
        ],
    )
    text = govt_report.to_csv(export)
    assert "'=HYPERLINK" in text, "aggregate CSV delivered an unescaped formula cell"
    assert "\n=HYPERLINK" not in text


_ID_HEADER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _raw_asgi_request(app: Any, headers: list[tuple[bytes, bytes]]) -> dict[bytes, bytes]:
    """Drive one GET through the ASGI interface with byte-exact headers.

    ``httpx`` refuses to send CR/LF inside a header value, so the middleware's
    sanitiser can only be exercised by speaking ASGI directly -- which is what
    a hostile proxy or a raw TCP client does.
    """
    sent: dict[str, Any] = {}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            sent["status"] = message["status"]
            sent["headers"] = message["headers"]

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), *headers],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }
    asyncio.run(app(scope, receive, send))
    return {name.lower(): value for name, value in sent["headers"]}


def test_raw_control_characters_in_request_id_are_replaced(tmp_path) -> None:
    app = make_client(tmp_path).app
    for hostile in (b"trace\r\nX-Injected: 1", b"nul\x00byte", b"a" * 65, b"bad$chars!"):
        headers = _raw_asgi_request(app, [(b"x-request-id", hostile)])
        echoed = headers[b"x-request-id"].decode("ascii")
        assert _ID_HEADER.fullmatch(echoed), f"hostile id {hostile!r} echoed as {echoed!r}"


def test_raw_valid_request_id_is_preserved(tmp_path) -> None:
    app = make_client(tmp_path).app
    headers = _raw_asgi_request(app, [(b"x-request-id", b"probe.trace_id-1")])
    assert headers[b"x-request-id"] == b"probe.trace_id-1"


def test_logged_newlines_cannot_forge_a_second_line() -> None:
    stream = io.StringIO()
    logger = logging.getLogger("tests.w2.sec08.probe")
    handler = logging.StreamHandler(stream)
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        json_log(
            logger,
            logging.WARNING,
            "probe_event",
            note="line1\nFAKE 2026-01-01 ERROR forged\r\nline2",
        )
    finally:
        logger.handlers = []

    raw = stream.getvalue()
    assert raw.count("\n") == 1, "a logged newline forged an extra physical line"
    assert "FAKE 2026-01-01 ERROR forged" in raw
    assert "\\n" in raw and "\\r" in raw


_TEMPLATE_PAYLOADS = ["{{1337*7}}", "${1337*7}", "<%= 1337*7 %>", "#{1337*7}"]
_EVALUATED = "9359"  # 1337*7 must never appear as a computed value


def _paper_with(text: str) -> dict:
    return {
        "exam_type": text,
        "class_level": "৯-১০",
        "subject": text,
        "marks": 1,
        "duration_min": 1,
        "chapters": [text],
        "questions": [{"text": text, "marks": 1, "options": [text, "খ"], "answer_index": 0}],
    }


def _html_escaped(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


@pytest.mark.parametrize("payload", _TEMPLATE_PAYLOADS)
def test_qp_html_never_evaluates_template_syntax(payload: str) -> None:
    html = render_qp_html(_paper_with(payload))
    assert _EVALUATED not in html
    assert payload in html or _html_escaped(payload) in html


@pytest.mark.parametrize("payload", _TEMPLATE_PAYLOADS)
def test_qp_pdf_never_evaluates_template_syntax(payload: str) -> None:
    data = render_qp_pdf(_paper_with(payload))
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert _EVALUATED not in text
    assert payload in text


def test_qp_html_escapes_markup_payloads() -> None:
    html = render_qp_html(_paper_with("<script>alert(1)</script>"))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
