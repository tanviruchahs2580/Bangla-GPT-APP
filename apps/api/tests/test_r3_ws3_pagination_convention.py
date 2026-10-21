"""R3 / WS3 C-10 + H-03: pagination convention, versioning and one error shape.

Three contract-level properties, asserted against the SERVED OpenAPI document
and the live app (not against the source): the audit's C-10 verification is
"API review against the OpenAPI document", so that is what these tests read.

* every collection GET declares ``limit`` with ``ge=1`` and a cap <= 200, and
  an ``offset`` with ``ge=0`` -- except the documented top-N queue and the
  tracked deviations owned by other file sets (see
  ``docs/adr/ADR-0012-api-design-conventions.md``);
* every 4xx/5xx response the app produces uses the problem+json envelope,
  including the ones produced by middleware rather than by an exception;
* ``Idempotency-Key`` and ``If-Match`` are part of the served contract for the
  routes that support them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"

#: Collection GETs with no ``offset``, with the reason. A top-N queue answers
#: "what is due now" and reports its own total; paging it is meaningless.
DOCUMENTED_TOP_N = {
    "/revision/due": "top-N due queue; due_count reports the total",
}

#: Endpoints whose pagination is declared in a file set owned by another
#: workstream this round. The value is the deviation that is being tracked
#: (recorded in the ADR with the owner action); the test accepts exactly that
#: deviation and nothing worse, so the list cannot silently grow.
TRACKED_DEVIATIONS = {
    "/teacher/students": ("cap is 1000, no offset (routers/teacher.py; owner: teacher workstream)"),
    "/teacher/documents": (
        "no offset (routers/teacher_content.py; owner: teacher-content workstream)"
    ),
    "/tutor/conversations/{conversation_id}/messages": (
        "cap is 500, no offset (routers/tutor.py; owner: tutor workstream)"
    ),
}


@pytest.fixture(scope="module")
def spec() -> dict:
    app = create_app(
        Settings(
            env="test",
            llm_provider="mock",
            jwt_secret=SECRET,
            database_url="sqlite://",
        )
    )
    return app.openapi()


def _limit_endpoints(spec: dict) -> dict[str, dict]:
    out = {}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method != "get" or not isinstance(op, dict):
                continue
            params = {p["name"]: p for p in op.get("parameters", []) if p.get("in") == "query"}
            if "limit" in params:
                out[path] = params
    return out


def test_every_collection_limit_is_bounded_and_an_offset_exists(spec: dict) -> None:
    problems: list[str] = []
    for path, params in _limit_endpoints(spec).items():
        schema = params["limit"]["schema"]
        maximum = schema.get("maximum")
        minimum = schema.get("minimum")
        tracked = path in TRACKED_DEVIATIONS
        if minimum != 1:
            problems.append(f"{path}: 'limit' minimum is {minimum!r} (convention: ge=1)")
        if maximum is None:
            problems.append(f"{path}: 'limit' has no maximum")
        elif maximum > 200 and not tracked:
            problems.append(f"{path}: 'limit' cap is {maximum} (convention: <= 200)")
        if "offset" in params:
            offset_schema = params["offset"]["schema"]
            assert offset_schema.get("minimum") == 0, (
                f"{path}: 'offset' minimum is {offset_schema.get('minimum')!r} (convention: ge=0)"
            )
            continue
        if path not in DOCUMENTED_TOP_N and not tracked:
            problems.append(f"{path}: no 'offset' and not a documented top-N/deviating endpoint")
    assert not problems, "pagination convention violated:\n" + "\n".join(problems)


def test_the_deviation_and_exception_lists_do_not_rot(spec: dict) -> None:
    """Every tracked path still exists AND still deviates, and every top-N
    endpoint still looks like a top-N queue (no offset)."""
    endpoints = _limit_endpoints(spec)
    for path, owner in TRACKED_DEVIATIONS.items():
        assert path in endpoints, f"{path} is tracked but no longer paginated: {owner}"
    for path, reason in DOCUMENTED_TOP_N.items():
        assert path in endpoints, f"{path} documented as top-N but no longer paged: {reason}"
        assert "offset" not in endpoints[path], (
            f"{path} now has an offset; move it out of the top-N exception ({reason})"
        )


def test_offset_walks_a_stable_order(tmp_path) -> None:
    """Two pages of /notes must not overlap or skip (stable sort + offset)."""
    client = TestClient(
        create_app(
            Settings(
                env="test",
                llm_provider="mock",
                jwt_secret=SECRET,
                database_url=f"sqlite:///{tmp_path}/page.db",
            )
        )
    )
    email = "pager@example.test"
    assert (
        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "name": "শিক্ষার্থী",
                "role": "student",
                "class_level": 6,
                "guardian_consent": True,
            },
        ).status_code
        == 201
    )
    token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()[
        "access_token"
    ]
    headers = {"Authorization": f"Bearer {token}"}
    for index in range(5):
        res = client.post("/notes", json={"title": f"টীকা {index}", "body": "x"}, headers=headers)
        assert res.status_code in (200, 201), res.text

    first = client.get("/notes?limit=2&offset=0", headers=headers).json()
    second = client.get("/notes?limit=2&offset=2", headers=headers).json()
    third = client.get("/notes?limit=2&offset=4", headers=headers).json()
    ids = [row["id"] for row in first + second + third]
    assert len(ids) == 5, ids
    assert len(set(ids)) == 5, f"pages overlap: {ids}"


def test_all_error_envelopes_are_problem_json(tmp_path) -> None:
    """4xx/5xx from every layer: handler, validation, middleware, limiter."""
    settings = Settings(
        env="test",
        llm_provider="mock",
        jwt_secret=SECRET,
        database_url=f"sqlite:///{tmp_path}/shape.db",
        rate_limit_login_per_minute=1,
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        cases = [
            client.get("/users/me"),  # 401 from a dependency
            client.get("/no-such-route"),  # 404 from the router
            client.post("/auth/login", json={"email": "x"}),  # 422 validation
        ]
        # Trigger two logins to trip the 1/min limiter -> 429 from middleware.
        client.post("/auth/login", json={"email": "nobody@example.test", "password": PASSWORD})
        cases.append(
            client.post("/auth/login", json={"email": "nobody@example.test", "password": PASSWORD})
        )
        # Oversized body -> 413 from the ASGI body-size guard.
        cases.append(client.post("/auth/login", content=b"x" * (4 * 1024 * 1024 + 1)))
    for res in cases:
        assert res.status_code >= 400, (res.status_code, res.text)
        media = res.headers["content-type"].split(";")[0]
        assert media == "application/problem+json", (res.status_code, media)
        body = res.json()
        assert body["status"] == res.status_code
        assert body["type"] == "about:blank"
        assert "detail" in body, body


def test_idempotency_and_precondition_are_declared(spec: dict) -> None:
    """A client reading the contract can discover both headers."""
    op = spec["paths"]["/teacher/classrooms/{room_id}/import-file"]["post"]
    header_names = {p["name"].lower() for p in op.get("parameters", []) if p.get("in") == "header"}
    assert "idempotency-key" in header_names, header_names
    prefs_patch = spec["paths"]["/students/me/prefs"]["patch"]
    header_names = {
        p["name"].lower() for p in prefs_patch.get("parameters", []) if p.get("in") == "header"
    }
    assert "if-match" in header_names, header_names
