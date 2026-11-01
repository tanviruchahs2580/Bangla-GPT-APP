"""SEC-09 execution: client-boundary probes against the running app.

Covers the four client-side attack classes the audit inferred:

* XSS containment: every response is JSON behind ``nosniff`` with a CSP that
  cannot execute attacker markup (the model-authored markdown payload set is
  rendered client-side by SafeMarkdown, whose vitest suite is the sanitizer
  guard -- see src/test/markdown.test.tsx);
* CSRF: the API authenticates with bearer headers only; no endpoint may set a
  cookie, so there is no ambient credential a cross-site form could ride;
* clickjacking: baseline framing headers plus ``frame-ancestors 'none'``;
* open redirect / SSRF: no endpoint issues a redirect from requester input,
  and no user-supplied text is ever fetched server-side -- proved with a live
  loopback HTTP listener that must receive zero requests.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2sec09"),
        jwt_secret="test-secret-0123456789abcdef0123456789",
        **overrides,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str = "student") -> None:
    payload: dict = {"email": email, "password": PASSWORD, "name": "শিক্ষার্থী", "role": role}
    if role == "student":
        payload.update({"class_level": 6, "guardian_consent": True})
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text


def _headers(client: TestClient, email: str) -> dict[str, str]:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.parametrize("path", ["/health", "/ready", "/no-such-route"])
def test_framing_is_denied_on_every_response(tmp_path, path: str) -> None:
    client = make_client(tmp_path)
    res = client.get(path)
    assert res.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in res.headers["Content-Security-Policy"]


def test_csp_forbids_inline_script_and_objects(tmp_path) -> None:
    client = make_client(tmp_path)
    res = client.get("/health")
    csp = res.headers["Content-Security-Policy"]
    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
    assert "'unsafe-inline'" not in script_src
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp


def test_no_endpoint_sets_a_cookie(tmp_path) -> None:
    """No cookie means no ambient credential, which is why CSRF is N/A."""
    client = make_client(tmp_path)
    _register(client, "nocookie@example.com")
    replies = [
        client.post("/auth/login", json={"email": "nocookie@example.com", "password": PASSWORD}),
        client.post("/auth/forgot", json={"email": "nocookie@example.com"}),
        client.get("/health"),
        client.post(
            "/auth/login", json={"email": "nocookie@example.com", "password": "wrong-pass"}
        ),
    ]
    assert replies[0].status_code == 200
    for res in replies:
        assert "set-cookie" not in res.headers, f"unexpected cookie on {res.request.url}"


def test_json_responses_are_nosniff(tmp_path) -> None:
    client = make_client(tmp_path)
    for res in (client.get("/health"), client.get("/no-such-route")):
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize(
    "path",
    ["/auth/login", "/auth/verify-email", "/auth/reset", "/auth/forgot"],
)
def test_no_redirect_from_requester_supplied_target(tmp_path, path: str) -> None:
    """No API route redirects; a next/redirect_uri parameter is inert."""
    client = make_client(tmp_path)
    res = client.get(
        path,
        params={"next": "https://evil.example/x", "redirect_uri": "https://evil.example/x"},
        follow_redirects=False,
    )
    assert res.status_code not in (301, 302, 303, 307, 308), res.text
    assert "location" not in res.headers


class _ProbeHandler(BaseHTTPRequestHandler):
    """Records any request that reaches the loopback listener."""

    hits: ClassVar[list[str]] = []

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        type(self).hits.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"probe")

    def log_message(self, *args: object) -> None:
        """Keep the test output clean."""


@pytest.fixture
def ssrf_target():
    _ProbeHandler.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/ssrf-probe"
    server.shutdown()
    server.server_close()


def test_user_text_is_never_fetched_server_side(tmp_path, ssrf_target: str) -> None:
    client = make_client(tmp_path)
    url = ssrf_target

    _register(client, "ssrf.student@example.com")
    student = _headers(client, "ssrf.student@example.com")
    client.post(
        "/tutor/ask",
        json={"question": f"এই ঠিকানাটি খুলে দেখো: {url}", "class_level": 6},
        headers=student,
    )
    conv = client.post(
        "/tutor/conversations",
        json={"title": url},
        headers=student,
    )
    assert conv.status_code == 201, conv.text
    client.get("/tutor/messages/search", params={"q": url}, headers=student)
    client.get("/search", params={"q": url}, headers=student)
    client.post("/auth/login", json={"email": url, "password": PASSWORD})

    _register(client, "ssrf.teacher@example.com", role="teacher")
    teacher = _headers(client, "ssrf.teacher@example.com")
    room = client.post(
        "/teacher/classrooms",
        json={"class_level": 6, "section": "S"},
        headers=teacher,
    )
    assert room.status_code == 201, room.text
    imported = client.post(
        f"/teacher/classrooms/{room.json()['id']}/import",
        json={"csv_text": f"{url},ssrf.roster@example.com"},
        headers=teacher,
    )
    assert imported.status_code == 200, imported.text

    # The sleep IS the subject: it is the window in which a forbidden
    # server-side fetch would have to reach the probe listener. Every
    # triggering request above is a synchronous TestClient round-trip, so any
    # fetch has already completed before this line; 1.0 s is margin for the
    # probe thread's scheduling only -- three orders of magnitude above the
    # handler's own single-digit-millisecond response time.
    time.sleep(1.0)
    assert _ProbeHandler.hits == [], f"server fetched user-controlled URL(s): {_ProbeHandler.hits}"


def test_tutor_answer_is_json_not_html(tmp_path) -> None:
    """A markdown payload echoed in an answer stays JSON data, not a document."""
    client = make_client(tmp_path)
    _register(client, "md@example.com")
    headers = _headers(client, "md@example.com")
    res = client.post(
        "/tutor/ask",
        json={"question": "What is <script>alert(1)</script> [[[", "class_level": 6},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/json")
    assert "<script>" not in res.text  # the mock never reflects the prompt
