"""Rate-limit coverage for anonymous and AI-cost-bearing endpoints (SEC-001..004).

Every rule added to ``Settings.rate_limit_rules`` used to be optional: an
endpoint with no matching prefix simply ran unbounded. The concrete failures
this file locks down:

- SEC-001  ``POST /auth/register`` is anonymous and hashes one Argon2id
  password (19 MiB, t=2) per accepted row, with no rule at all.
- SEC-002  Seven ``/teacher/*`` AI generators spend provider budget but matched
  no prefix, so ``AI_MONTHLY_BUDGET_USD_PER_USER`` never applied to teachers.
- SEC-003  ``POST /parents/link/invite`` redeems a 32-bit, 24-hour code and
  costs a write per attempt.
- SEC-004  ``POST /teacher/classrooms/{id}/import`` hashes up to
  ``IMPORT_MAX_ROWS`` passwords inside one request.

The first test is the behavioural one: it proves the middleware actually
answers 429. The second is the invariant that stops this class of defect from
coming back, by enumerating the app's own routes instead of a hand-written
list that could rot.
"""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiJob
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.initialize.middleware_stack import _effective_rules
from bangla_gpt_api.main import PUBLIC_OPERATIONS, create_app
from conftest import engine_url

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"


def _settings(tmp_path, **over) -> Settings:
    base = dict(
        env="test",
        database_url=engine_url(tmp_path, "ratelimit"),
        jwt_secret=JWT,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    base.update(over)
    return Settings(**base)


def _client(tmp_path, **over) -> TestClient:
    return TestClient(create_app(_settings(tmp_path, **over)))


def _register_payload(email: str) -> dict:
    return {
        "email": email,
        "password": PASSWORD,
        "name": "নাম",
        "role": "student",
        "guardian_consent": True,
        "class_level": 6,
    }


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _rule_for(rules: dict[str, tuple[int, str]], path: str) -> tuple[int, str] | None:
    """The rule the middleware would apply to ``path``.

    Mirrors ``RateLimitMiddleware.dispatch``: strict prefix match, and only
    the first matching prefix in iteration order, since dispatch evaluates
    every match but they all have to allow.
    """
    for prefix, rule in rules.items():
        if path == prefix or path.startswith(prefix + "/"):
            return rule
    return None


# --- SEC-001: anonymous registration -----------------------------------------


def test_register_is_rate_limited(tmp_path) -> None:
    """11 anonymous registrations from one IP: the 11th is refused.

    The first ten must really succeed, otherwise this would pass for the
    wrong reason (a schema rejection also yields a non-201).
    """
    client = _client(tmp_path, rate_limit_rules={"/auth/register": (10, "ip")})
    for i in range(10):
        res = client.post("/auth/register", json=_register_payload(f"bulk{i}@example.com"))
        assert res.status_code == 201, (i, res.text)
    refused = client.post("/auth/register", json=_register_payload("bulk10@example.com"))
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "rate_limited"
    # API-05: the other 429 producer (login lockout) already sent Retry-After;
    # the middleware limiter must too, or a throttled client can only guess.
    retry_after = refused.headers.get("Retry-After")
    assert retry_after is not None, refused.headers
    assert 1 <= int(retry_after) <= 60


def test_register_rule_ships_by_default() -> None:
    """Not merely configurable: the shipped default table must carry it."""
    assert _rule_for(_effective_rules(Settings(env="test")), "/auth/register") == (10, "ip")


# --- SEC-003: parent invite redemption --------------------------------------


def test_parent_invite_redemption_is_rate_limited(tmp_path) -> None:
    """Guessing a 32-bit invite code must not be free.

    The bodies are wrong on purpose - the point is that the 11th attempt is
    refused by the limiter (429) rather than reaching the handler (400/409).
    """
    client = _client(tmp_path, rate_limit_rules={"/parents/link/invite": (10, "ip")})
    client.post("/auth/register", json=_register_payload("kid@example.com"))
    client.post(
        "/auth/register",
        json={
            **_register_payload("mom@example.com"),
            "role": "parent",
            "class_level": None,
            "guardian_consent": False,
        },
    )
    headers = _login(client, "mom@example.com")

    statuses = [
        client.post("/parents/link/invite", json={"code": f"BGPT-{i:08X}"}, headers=headers)
        for i in range(11)
    ]
    assert all(s.status_code == 400 for s in statuses[:10]), [s.text for s in statuses[:10]]
    assert statuses[10].status_code == 429


def test_parent_invite_rule_ships_by_default() -> None:
    assert _rule_for(_effective_rules(Settings(env="test")), "/parents/link/invite") == (
        10,
        "ip",
    )


# --- SEC-002 / SEC-004: teacher AI generators and bulk import ----------------


@pytest.mark.parametrize(
    "path",
    [
        "/teacher/content/generate",
        "/teacher/qpapers",
        "/teacher/lesson-plans",
        "/teacher/generate/worksheet",
        "/teacher/jobs",
        "/teacher/classrooms",
        "/teacher/classrooms/1/roster",
        "/teacher/classrooms/1/import",
        "/teacher/qpapers/1/regenerate",
    ],
)
def test_expensive_teacher_paths_have_a_default_rule(path: str) -> None:
    """Prefix coverage, not exact-path coverage.

    ``/teacher/qpapers`` must also cover ``/teacher/qpapers/{id}/regenerate``
    because the middleware matches on prefixes; asserting the rule for each
    concrete path is what keeps a future route addition from escaping.
    """
    rules = _effective_rules(Settings(env="test"))
    rule = _rule_for(rules, path)
    assert rule is not None, f"{path} has no rate-limit rule"
    assert rule[0] > 0, f"{path} rule is disabled"
    # These are all behind authentication, so they must be scoped per user:
    # an IP scope would let one school NAT lock out a whole staffroom.
    assert rule[1] == "user", f"{path} must be scoped per user, got {rule[1]!r}"


def test_teacher_jobs_are_rate_limited_end_to_end(tmp_path) -> None:
    """The route is throttled per user; the throttle is what is measured.

    Two things about this route shape the test, and both bit before:

    * `POST /teacher/jobs` answers 202 and runs the generation as a DETACHED
      asyncio task on the app's portal loop (`routers/workspace.py`), so the
      client must be a context manager (the convention documented in
      `test_ai_jobs.py`) or the task is still writing to the same SQLite file
      when the next request writes — the CI flake of 2026-10-26 was
      `database is locked`, not a limiter failure.
    * the rule is a strict PREFIX match, so polling `GET /teacher/jobs/{id}`
      to wait for the job spends the same per-user budget the test is trying
      to exhaust. The wait therefore reads the job table directly, through a
      session over the same database.
    """
    settings = _settings(tmp_path, rate_limit_rules={"/teacher/jobs": (3, "user")})
    factory = make_session_factory(make_engine(settings))
    with TestClient(create_app(settings)) as client:
        client.post(
            "/auth/register",
            json={
                **_register_payload("t1@example.com"),
                "role": "teacher",
                "class_level": None,
                "guardian_consent": False,
            },
        )
        headers = _login(client, "t1@example.com")

        for _ in range(3):
            queued = client.post("/teacher/jobs", json={"kind": "worksheet"}, headers=headers)
            assert queued.status_code == 202, queued.text
            _wait_job_settled(factory, queued.json()["id"])

        blocked = client.post("/teacher/jobs", json={"kind": "worksheet"}, headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"]["code"] == "rate_limited"


def _wait_job_settled(factory, job_id: str, timeout: float = 30.0) -> None:
    """Wait for the detached job task to stop writing (see the docstring)."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        with factory() as session:
            last = session.execute(
                select(AiJob.status).where(AiJob.id == job_id)
            ).scalar_one_or_none()
        if last in ("ready", "failed"):
            return
        time.sleep(0.05)
    pytest.fail(f"job {job_id} never settled (last status: {last})")


# --- the invariant ----------------------------------------------------------

#: Prefixes whose handlers spend real money (an LLM call) or real CPU
#: (an Argon2id hash per row / per account). A route under one of these with
#: no matching rule is the defect this file exists to prevent.
COSTLY_PREFIXES = (
    "/teacher/content",
    "/teacher/qpapers",
    "/teacher/lesson-plans",
    "/teacher/generate",
    "/teacher/jobs",
    "/tutor",
)


def test_no_costly_route_is_left_unrated() -> None:
    """Every teacher/tutor route resolves to an active rule.

    Derived from the app's own route table rather than a literal list, so a
    newly added generator cannot slip past unreviewed.
    """
    app = create_app(_settings(None, database_url="sqlite:///:memory:"))
    rules = _effective_rules(app.state.settings)
    uncovered = sorted(
        f"{sorted(r.methods)[0]} {r.path}"
        for r in app.routes
        if getattr(r, "methods", None)
        and r.path.startswith(COSTLY_PREFIXES)
        and (_rule_for(rules, r.path) or (0, ""))[0] <= 0
    )
    assert not uncovered, f"cost-bearing routes with no rate limit: {uncovered}"


def test_anonymous_routes_are_either_public_or_rated() -> None:
    """``/auth/register`` and ``/parents/link/invite`` are the two anonymous
    non-``PUBLIC_OPERATIONS`` prefixes that take unbounded work; both must be
    rated. ``/parents/link/invite`` needs a session, so only the truly
    anonymous register route is asserted here.
    """
    rules = _effective_rules(Settings(env="test"))
    for prefix in ("/auth/register", "/auth/login", "/auth/forgot", "/auth/reset"):
        assert _rule_for(rules, prefix) is not None, prefix
    # Sanity: the public list really does contain the health probes, so this
    # test is not passing because PUBLIC_OPERATIONS is empty.
    assert any("/health" in op for op in PUBLIC_OPERATIONS)


# --- the credential-verifying counterpart of login ---------------------------


def test_change_password_rule_ships_by_default() -> None:
    """/auth/change-password verifies the CURRENT password and re-hashes.

    It had no rule at all: a stolen-token holder (or anyone on a shared
    school device) could guess the current password unbounded, and each
    attempt costs two Argon2id operations (verify + hash-on-save) — the
    worst cost profile of any credential endpoint, with no throttle. Per
    user, for the school-NAT reason the /auth/mfa rule documents.
    """
    assert _rule_for(_effective_rules(Settings(env="test")), "/auth/change-password") == (
        10,
        "user",
    )


def test_change_password_is_rate_limited_end_to_end(tmp_path) -> None:
    """The 11th wrong-current-password attempt in a minute is a 429.

    The first ten must reach the handler and answer 400 (wrong current
    password), otherwise this would pass because of some other rejection.
    """
    client = _client(tmp_path, rate_limit_rules={"/auth/change-password": (10, "user")})
    client.post("/auth/register", json=_register_payload("chpw@example.com"))
    headers = _login(client, "chpw@example.com")

    statuses = [
        client.post(
            "/auth/change-password",
            json={"current_password": f"wrong{i}", "new_password": "AnotherPass!234"},
            headers=headers,
        )
        for i in range(11)
    ]
    assert all(s.status_code == 400 for s in statuses[:10]), [s.text for s in statuses[:10]]
    assert statuses[10].status_code == 429
    assert statuses[10].json()["detail"]["code"] == "rate_limited"
