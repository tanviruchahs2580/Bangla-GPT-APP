"""RFC 9457 problem details (C-06 / AUD-CD-04).

The API's error contract used to be two ad-hoc shapes -- a plain string for
auth guards and ``{"code","message"}`` for business rules -- with no standard
media type and no machine-readable status/title. The handlers registered in
``create_app`` now render every HTTPException and every 422 as
``application/problem+json`` while keeping ``detail`` byte-for-byte as it was,
so nothing that read the old body breaks.

These tests pin both halves: the RFC members a generic client needs, and the
backward-compatible ``detail`` each existing client reads. The app is built by
the same factory the rest of the suite uses; nothing is monkeypatched.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app


def _client() -> TestClient:
    settings = Settings(env="test", llm_provider="mock")
    return TestClient(create_app(settings))


def _assert_problem(res, status: int) -> dict:
    assert res.status_code == status, res.text
    assert res.headers["content-type"].startswith("application/problem+json"), res.headers
    body = res.json()
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert isinstance(body["title"], str) and body["title"]
    assert body["instance"].startswith("/")
    assert "detail" in body
    return body


def test_missing_credentials_is_problem_json_with_a_string_detail() -> None:
    with _client() as client:
        body = _assert_problem(client.get("/users/me"), 401)
    # The auth-guard contract: a string detail, exactly as before.
    assert isinstance(body["detail"], str) and body["detail"]


def test_unknown_route_is_problem_json() -> None:
    with _client() as client:
        _assert_problem(client.get("/definitely-not-a-route"), 404)


def test_coded_business_rule_keeps_its_detail_and_mirrors_the_code() -> None:
    """409 email_taken: ``{code,message}`` unchanged, ``code`` also top-level."""
    payload = {
        "email": "problem-details@example.com",
        "password": "correct-horse-battery",
        "name": "রহিম",
        "role": "student",
        "guardian_consent": True,
        "class_level": 7,
    }
    with _client() as client:
        first = client.post("/auth/register", json=payload)
        assert first.status_code in (201, 409), first.text
        second = client.post("/auth/register", json=payload)
        body = _assert_problem(second, 409)
    assert body["detail"]["code"] == "email_taken"
    assert body["code"] == "email_taken"
    assert body["detail"]["message"]


def test_validation_error_is_problem_json_and_keeps_the_error_list() -> None:
    with _client() as client:
        body = _assert_problem(client.post("/auth/login", json={"email": "not-an-email"}), 422)
    assert isinstance(body["detail"], list) and body["detail"]
    assert body["detail"][0]["loc"]


def test_auth_guard_headers_survive_the_wrapper() -> None:
    """Handler re-emits exception headers: the 401 carries WWW-Authenticate."""
    with _client() as client:
        res = client.get("/users/me")
    assert res.status_code == 401
    assert "www-authenticate" in {k.lower() for k in res.headers}
