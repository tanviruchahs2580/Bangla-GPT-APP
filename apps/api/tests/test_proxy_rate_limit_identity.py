"""S-001: the client IP behind a trusted proxy is the entry the proxy appended.

The shipped nginx appends to X-Forwarded-For (``$proxy_add_x_forwarded_for``),
so the trustworthy element is the LAST one; reading the first (the old code)
let any client rotate a spoofed prefix and bypass every IP-scoped limit. These
tests pin the parser and the end-to-end rate-limit identity.
"""

from fastapi.testclient import TestClient
from starlette.requests import Request

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.middleware import _client_ip

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"


def _request(headers: dict[str, str] | None = None, peer: str = "10.0.0.9") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "query_string": b"",
            "headers": raw,
            "client": (peer, 4321),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


# --- the parser ---------------------------------------------------------------


def test_without_xff_the_transport_peer_is_used() -> None:
    assert _client_ip(_request(), trust_proxy=True) == "10.0.0.9"
    assert _client_ip(_request(), trust_proxy=False) == "10.0.0.9"


def test_single_entry_xff_is_the_identity() -> None:
    request = _request({"X-Forwarded-For": "203.0.113.7"})
    assert _client_ip(request, trust_proxy=True) == "203.0.113.7"


def test_spoofed_prefix_is_ignored_and_the_appended_peer_wins() -> None:
    """nginx appends the real peer after whatever the client sent."""
    request = _request({"X-Forwarded-For": "1.2.3.4, 203.0.113.9"})
    assert _client_ip(request, trust_proxy=True) == "203.0.113.9"


def test_multiple_forwarded_hops_only_the_last_counts() -> None:
    request = _request({"X-Forwarded-For": "1.2.3.4, 198.51.100.1, 203.0.113.9"})
    assert _client_ip(request, trust_proxy=True) == "203.0.113.9"


def test_garbage_xff_falls_back_to_the_transport_peer() -> None:
    request = _request({"X-Forwarded-For": "not-an-ip, also::bad"})
    assert _client_ip(request, trust_proxy=True) == "10.0.0.9"


def test_invalid_trailing_entries_are_skipped_to_the_last_valid_ip() -> None:
    # A trailing element the proxy did not write (no valid IP) must not be
    # accepted as an identity; the last valid element is used instead.
    request = _request({"X-Forwarded-For": "203.0.113.7, hostname.example"})
    assert _client_ip(request, trust_proxy=True) == "203.0.113.7"


def test_ports_and_whitespace_are_not_identities() -> None:
    assert (
        _client_ip(_request({"X-Forwarded-For": " 203.0.113.7:8443 "}), trust_proxy=True)
        == "10.0.0.9"
    )
    assert (
        _client_ip(_request({"X-Forwarded-For": "  ,  ,203.0.113.9  "}), trust_proxy=True)
        == "203.0.113.9"
    )


def test_ipv6_entries_are_accepted() -> None:
    request = _request({"X-Forwarded-For": "1.2.3.4, 2001:db8::1"})
    assert _client_ip(request, trust_proxy=True) == "2001:db8::1"


def test_untrusted_proxy_mode_ignores_the_header_entirely() -> None:
    request = _request({"X-Forwarded-For": "203.0.113.7"})
    assert _client_ip(request, trust_proxy=False) == "10.0.0.9"


# --- the rate-limit identity --------------------------------------------------


def _client(tmp_path, **over) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/proxyip.db",
        jwt_secret=JWT,
        rate_limit_login_per_minute=2,
        **over,
    )
    return TestClient(create_app(settings))


def _attempt(client: TestClient, forwarded: str) -> int:
    return client.post(
        "/auth/login",
        json={"email": "nobody@example.test", "password": "definitely-wrong"},
        headers={"X-Forwarded-For": forwarded},
    ).status_code


def test_spoofed_prefix_cannot_rotate_the_rate_limit_identity(tmp_path) -> None:
    """Ten different spoofed prefixes behind the same real client share one
    bucket and trip the limit; the appended entry is what is counted."""
    client = _client(tmp_path, trust_proxy_headers=True)
    codes = [_attempt(client, f"203.0.113.{i}, 198.51.100.7") for i in range(2)]
    assert codes == [401, 401]
    blocked = _attempt(client, "203.0.113.99, 198.51.100.7")
    assert blocked == 429, "rotating the spoofed prefix bypassed the IP limit"

    # A DIFFERENT genuine client (different appended entry) keeps its budget.
    assert _attempt(client, "203.0.113.1, 198.51.100.8") == 401


def test_garbage_only_xff_does_not_forge_an_identity(tmp_path) -> None:
    """With nothing valid in the header the transport peer is counted, so a
    caller cannot mint unlimited fresh identities by sending junk."""
    client = _client(tmp_path, trust_proxy_headers=True)
    codes = [_attempt(client, f"garbage-{i}") for i in range(2)]
    assert codes == [401, 401]
    assert _attempt(client, "garbage-again") == 429
