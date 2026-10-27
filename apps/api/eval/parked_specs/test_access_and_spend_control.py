"""Access-control and spend-control regression tests.

Two defects are pinned here:

1. `PATCH /admin/users/{id}/role` changed the role in the database but left
   every outstanding access token valid. A demoted -- or suspended -- user kept
   full access until their token expired on its own, which is precisely
   backwards for an urgent offboarding.

2. Six routes trigger a real provider call and none of them consulted the
   monthly AI budget, while the tutor routes did. Teacher content generation
   was therefore unmetered spend behind a single account.
"""

import time

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
ADMIN_EMAIL = "root@example.com"
SECRET = "test-secret-0123456789abcdef0123456789"


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/access.db",
        jwt_secret=SECRET,
        admin_email=ADMIN_EMAIL,
        admin_password=PASSWORD,
        force_admin_password_change=False,
        **overrides,
    )


def make_client(tmp_path, **overrides) -> TestClient:
    return TestClient(create_app(_settings(tmp_path, **overrides)))


def _session(tmp_path):
    return make_session_factory(make_engine(_settings(tmp_path)))()


def _register(client: TestClient, email: str, role: str = "student") -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Sample User", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _token(client: TestClient, email: str) -> str:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _headers(client: TestClient, email: str) -> dict:
    return {"Authorization": f"Bearer {_token(client, email)}"}


# ---------------------------------------------------------------------------
# 1. A role change must revoke live sessions
# ---------------------------------------------------------------------------


def _stale_token(tmp_path, email: str, *, seconds_ago: int = 120) -> str:
    """Mint a token whose ``iat`` predates any change made now.

    The revocation check is second-precision by design (see deps.get_current_user):
    a token minted in the same second as the rotation survives, because PyJWT
    rejects a future ``iat``. Minting in the past makes the assertion
    deterministic instead of racing the clock.
    """
    from bangla_gpt_api.auth.security import create_access_token
    from bangla_gpt_api.db.models import User

    with _session(tmp_path) as db:
        user = db.query(User).filter(User.email == email).one()
        return create_access_token(
            user,
            settings=_settings(tmp_path),
            issued_at=int(time.time()) - seconds_ago,
        )


def test_role_change_invalidates_the_targets_existing_token(tmp_path) -> None:
    with make_client(tmp_path) as client:
        root = _headers(client, ADMIN_EMAIL)
        created = _register(client, "target@example.com")
        stale = {"Authorization": f"Bearer {_stale_token(tmp_path, 'target@example.com')}"}

        # The token works before the change...
        assert client.get("/users/me", headers=stale).status_code == 200

        patched = client.patch(
            f"/admin/users/{created['user_id']}/role",
            json={"role": "teacher"},
            headers=root,
        )
        assert patched.status_code == 200, patched.text

        # ...and must not afterwards. Offboarding has to take effect
        # immediately, not when the token happens to expire.
        after = client.get("/users/me", headers=stale)
        assert after.status_code == 401, (
            "the pre-existing token survived a role change; a demoted user "
            "would keep full access until natural expiry"
        )


def test_role_change_bumps_the_session_epoch(tmp_path) -> None:
    """The mechanism itself, independent of any token's ``iat``."""
    with make_client(tmp_path) as client:
        root = _headers(client, ADMIN_EMAIL)
        created = _register(client, "epoch@example.com")

        client.patch(
            f"/admin/users/{created['user_id']}/role",
            json={"role": "teacher"},
            headers=root,
        )

        from bangla_gpt_api.db.models import User

        with _session(tmp_path) as db:
            user = db.get(User, created["user_id"])
            assert user.sessions_invalidated_at is not None
            assert user.role == "teacher"


def test_role_change_audit_still_records_the_transition(tmp_path) -> None:
    """Revocation must not come at the cost of the audit trail."""
    with make_client(tmp_path) as client:
        root = _headers(client, ADMIN_EMAIL)
        created = _register(client, "audited@example.com")

        client.patch(
            f"/admin/users/{created['user_id']}/role",
            json={"role": "teacher"},
            headers=root,
        )

        audit = client.get("/admin/audit", headers=root)
        assert audit.status_code == 200
        assert "role_change" in [row["action"] for row in audit.json()["rows"]]


def test_role_change_takes_effect_on_the_next_login(tmp_path) -> None:
    with make_client(tmp_path) as client:
        root = _headers(client, ADMIN_EMAIL)
        created = _register(client, "promoted@example.com")

        client.patch(
            f"/admin/users/{created['user_id']}/role",
            json={"role": "teacher"},
            headers=root,
        )

        me = client.get("/users/me", headers=_headers(client, "promoted@example.com"))
        assert me.status_code == 200
        assert me.json()["role"] == "teacher"


def test_unchanged_role_does_not_grant_a_second_living_session(tmp_path) -> None:
    """Re-assigning the role the user already has still revokes.

    The epoch is the only lever available, and making the revocation
    conditional on an actual role delta would leave an offboarding path open
    to any caller that sends back the role the target already has.
    """
    with make_client(tmp_path) as client:
        root = _headers(client, ADMIN_EMAIL)
        created = _register(client, "same-role@example.com")
        stale = {"Authorization": f"Bearer {_stale_token(tmp_path, 'same-role@example.com')}"}

        assert client.get("/users/me", headers=stale).status_code == 200

        client.patch(
            f"/admin/users/{created['user_id']}/role",
            json={"role": "student"},
            headers=root,
        )

        assert client.get("/users/me", headers=stale).status_code == 401


# ---------------------------------------------------------------------------
# 2. Every provider-calling route must respect the budget
# ---------------------------------------------------------------------------

# Payload shapes are borrowed from the suites that already exercise each route
# successfully (tests/test_qpaper.py, test_lesson_plan.py, test_content_engine.py).
# A malformed body would 422 before reaching the handler, which would make the
# budget assertion pass for the wrong reason if we only checked "not 201".
GENERATION_ROUTES = [
    (
        "/teacher/qpapers",
        {
            "class_level": 6,
            "subject": "science",
            "chapters": ["কোষ"],
            "exam_type": "Exam 2026",
            "marks": 10,
            "duration_min": 10,
        },
    ),
    (
        "/teacher/lesson-plans",
        {"class_level": 6, "subject": "science", "chapter": "কোষ"},
    ),
    (
        "/teacher/content/generate",
        {"class_level": 6, "subject": "science", "chapter": "কোষ"},
    ),
    ("/teacher/jobs", {"kind": "lesson_plan", "payload": {}}),
]


def _spend_budget(tmp_path, user_id: int) -> None:
    """Push the user's ledger total above the (near-zero) configured cap."""
    from bangla_gpt_api.db.models import AiUsage

    with _session(tmp_path) as db:
        db.add(
            AiUsage(
                user_id=user_id,
                route="seed",
                model="seed",
                prompt_tokens=10_000,
                completion_tokens=10_000,
                estimated_cost_usd=5.0,
            )
        )
        db.commit()


@pytest.mark.parametrize("path,body", GENERATION_ROUTES, ids=[p for p, _ in GENERATION_ROUTES])
def test_generation_routes_refuse_once_the_budget_is_spent(tmp_path, path, body) -> None:
    """A tiny positive budget must bite on every generation route.

    A route that ignores the budget answers with its normal validation error
    or a provider response instead of 429 -- which is how the gap showed up.
    """
    with make_client(tmp_path, ai_monthly_budget_usd_per_user=0.0000001) as client:
        created = _register(client, "spender@example.com", role="teacher")
        headers = _headers(client, "spender@example.com")
        _spend_budget(tmp_path, created["user_id"])

        res = client.post(path, json=body, headers=headers)

        assert res.status_code == 429, f"{path} answered {res.status_code}, expected 429"
        assert res.json()["detail"]["code"] == "ai_budget_exceeded"


@pytest.mark.parametrize("path,body", GENERATION_ROUTES, ids=[p for p, _ in GENERATION_ROUTES])
def test_generation_routes_remain_available_when_no_budget_is_set(tmp_path, path, body) -> None:
    """Default configuration (budget disabled) must not start refusing work."""
    with make_client(tmp_path) as client:
        created = _register(client, "free@example.com", role="teacher")
        headers = _headers(client, "free@example.com")
        assert created["user_id"]

        res = client.post(path, json=body, headers=headers)

        assert res.status_code != 429, "the budget must stay off unless configured"


def test_tutor_routes_still_honour_the_budget(tmp_path) -> None:
    """The pre-existing gate must keep working after the refactor."""
    with make_client(tmp_path, ai_monthly_budget_usd_per_user=0.0000001) as client:
        created = _register(client, "student-spender@example.com")
        headers = _headers(client, "student-spender@example.com")
        _spend_budget(tmp_path, created["user_id"])

        res = client.post(
            "/tutor/ask",
            json={"question": "ভগ্নাংশ কী?", "class_level": 6, "subject": "mathematics"},
            headers=headers,
        )

        assert res.status_code == 429
        assert res.json()["detail"]["code"] == "ai_budget_exceeded"
