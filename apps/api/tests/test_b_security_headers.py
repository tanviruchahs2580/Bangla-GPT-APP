"""AUD-B-08 / AUD-B-13 / AUD-B-09: response-header and error-shape contract.

Three coupled behaviours, all observable on a real ``TestClient`` response:

* every baseline hardening header is present -- including the
  deny-by-default ``Permissions-Policy`` that was missing (AUD-B-08) -- and
  it is present on success *and* error responses, not only on 200s;
* a limiter 429 carries ``Retry-After`` (AUD-B-13), so a well-behaved client
  backs off instead of deepening the limit;
* the error body stays the coded ``{"detail": ...}`` envelope -- the accepted
  RFC 9457 deviation recorded in ``SECURITY.md`` (AUD-B-09) -- rather than
  silently drifting to an unlabelled shape.

The header list is read from the middleware class itself, so adding a header
to ``BASELINE_HEADERS`` extends this test instead of bypassing it.
"""

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.middleware import RATE_LIMIT_WINDOW_SECONDS, SecurityHeadersMiddleware

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"


def _client(tmp_path, **over) -> TestClient:
    base = dict(
        env="test",
        database_url=f"sqlite:///{tmp_path}/b_headers.db",
        jwt_secret=JWT,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    base.update(over)
    return TestClient(create_app(Settings(**base)))


def _assert_baseline_headers(res) -> None:
    for header, value in SecurityHeadersMiddleware.BASELINE_HEADERS.items():
        assert res.headers.get(header) == value, f"{header} missing on {res.status_code}"


def test_baseline_headers_on_success(tmp_path) -> None:
    client = _client(tmp_path)
    res = client.get("/health")
    assert res.status_code == 200
    _assert_baseline_headers(res)


def test_permissions_policy_is_deny_by_default(tmp_path) -> None:
    """AUD-B-08: the API needs no browser feature, so every one is denied."""
    client = _client(tmp_path)
    policy = client.get("/health").headers.get("Permissions-Policy")
    assert policy, "Permissions-Policy must be served on every API response"
    for feature in ("camera", "microphone", "geolocation", "payment", "usb"):
        assert f"{feature}=()" in policy, f"{feature} is not denied in: {policy}"


def test_headers_survive_error_responses(tmp_path) -> None:
    """A 401 and a 404 must carry the same hardening as a 200."""
    client = _client(tmp_path)
    for res in (client.get("/users/me"), client.get("/no-such-route")):
        assert res.status_code in (401, 404)
        _assert_baseline_headers(res)


def test_rate_limit_429_carries_retry_after(tmp_path) -> None:
    """AUD-B-13: the limiter refusal tells the caller when to come back."""
    client = _client(tmp_path, rate_limit_login_per_minute=1)
    payload = {"email": "nobody@example.com", "password": PASSWORD}
    first = client.post("/auth/login", json=payload)
    assert first.status_code == 401, first.text
    refused = client.post("/auth/login", json=payload)
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "rate_limited"
    assert refused.headers.get("Retry-After") == str(RATE_LIMIT_WINDOW_SECONDS)


def test_error_envelope_is_coded_detail_json(tmp_path) -> None:
    """AUD-B-09: the accepted error contract, pinned against silent drift."""
    client = _client(tmp_path)
    cases = (
        (client.get("/users/me"), 401),
        (client.get("/no-such-route"), 404),
        (client.post("/auth/login", json={"email": "x"}), 422),
    )
    for res, expected in cases:
        assert res.status_code == expected, res.text
        # C-06/AUD-CD-04: errors render as RFC 9457 problem+json now. The
        # envelope stays JSON and the `detail` contract is unchanged; only the
        # media type gained its standard name.
        assert res.headers["content-type"].split(";")[0] in {
            "application/json",
            "application/problem+json",
        }, res.headers
        body = res.json()
        assert "detail" in body, f"error body is not the documented envelope: {body}"
    # Framework-level refusals carry a plain string in ``detail`` (FastAPI's
    # HTTPException), handler refusals carry the coded dict; both are the
    # documented envelope and neither leaks internals.
    detail = client.get("/users/me").json()["detail"]
    assert (isinstance(detail, str) and detail) or isinstance(detail, dict)
