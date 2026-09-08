"""B3/B17 — password reset, change-password and forced rotation flows."""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import PasswordReset
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/reset.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=True,
        **overrides,
    )
    return TestClient(create_app(settings))


@pytest.fixture
def client(tmp_path) -> TestClient:
    return make_client(tmp_path)


def _login_headers(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    body = res.json()
    return {
        "Authorization": f"Bearer {body['access_token']}",
        "_must_change_password": body.get("must_change_password"),
    }


def _capture_reset_token(client: TestClient, email: str, caplog: pytest.LogCaptureFixture) -> str:
    with caplog.at_level(logging.INFO):
        response = client.post("/auth/forgot", json={"email": email})
    assert response.status_code == 202
    for record in reversed(caplog.records):
        try:
            payload = json.loads(record.getMessage())
        except ValueError:
            continue
        if payload.get("event") == "password_reset_token_console":
            token = payload["token"]
            caplog.clear()
            return token
    raise AssertionError("console reset token was not logged in non-production")


def test_forgot_is_generic_for_unknown_email(client: TestClient) -> None:
    known = client.post("/auth/forgot", json={"email": "root@example.com"})
    unknown = client.post("/auth/forgot", json={"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"status": "accepted"}


def test_reset_flow_changes_password_single_use(
    client: TestClient, tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    token = _capture_reset_token(client, "root@example.com", caplog)

    res = client.post("/auth/reset", json={"token": token, "new_password": "new-strong-pass-9"})
    assert res.status_code == 200, res.text
    fresh = res.json()["access_token"]
    assert fresh

    # old password no longer works; new one does
    assert (
        client.post(
            "/auth/login", json={"email": "root@example.com", "password": PASSWORD}
        ).status_code
        == 401
    )
    ok = client.post(
        "/auth/login", json={"email": "root@example.com", "password": "new-strong-pass-9"}
    )
    assert ok.status_code == 200
    assert ok.json()["must_change_password"] is False

    # single use: replaying the same token fails
    replay = client.post("/auth/reset", json={"token": token, "new_password": "another-pass-77"})
    assert replay.status_code == 400


def test_reset_rejects_expired_token(client: TestClient, tmp_path) -> None:
    client.post("/auth/forgot", json={"email": "root@example.com"})
    # fabricate an already-expired row directly in the DB
    from sqlalchemy import select as _select

    from bangla_gpt_api.db.session import make_engine, make_session_factory

    engine = make_engine(Settings(database_url=f"sqlite:///{tmp_path}/reset.db"))
    factory = make_session_factory(engine)
    with factory() as db:
        row = db.execute(_select(PasswordReset).limit(1)).scalar_one()
        row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        db.commit()

    res = client.post("/auth/reset", json={"token": "x" * 40, "new_password": "whatever-123"})
    assert res.status_code == 400


def test_new_request_invalidates_previous_tokens(
    client: TestClient, tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    first = _capture_reset_token(client, "root@example.com", caplog)
    second = _capture_reset_token(client, "root@example.com", caplog)
    assert first != second

    used_old = client.post("/auth/reset", json={"token": first, "new_password": "should-fail-11"})
    assert used_old.status_code == 400

    works = client.post("/auth/reset", json={"token": second, "new_password": "fresh-pass-2299"})
    assert works.status_code == 200


def test_change_password_requires_current_and_rotates(client: TestClient) -> None:
    headers_map = _login_headers(client, "root@example.com")
    headers = {k: v for k, v in headers_map.items() if not k.startswith("_")}
    assert headers_map["_must_change_password"] is True  # bootstrap admin must rotate

    wrong = client.post(
        "/auth/change-password",
        json={"current_password": "wrong", "new_password": "rotated-pass-1"},
        headers=headers,
    )
    assert wrong.status_code == 400

    same = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
        headers=headers,
    )
    assert same.status_code == 422

    changed = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "rotated-pass-1"},
        headers=headers,
    )
    assert changed.status_code == 200
    assert changed.json()["must_change_password"] is False

    relogin = client.post(
        "/auth/login", json={"email": "root@example.com", "password": "rotated-pass-1"}
    )
    assert relogin.status_code == 200
    assert relogin.json()["must_change_password"] is False


def test_force_change_blocks_other_endpoints_until_rotated(tmp_path) -> None:
    client = make_client(tmp_path)
    login = client.post("/auth/login", json={"email": "root@example.com", "password": PASSWORD})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert login.json()["must_change_password"] is True

    blocked = client.get("/admin/users", headers=headers)
    assert blocked.status_code == 403
    blocked_ask = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6},
        headers=headers,
    )
    assert blocked_ask.status_code == 403

    # exempt endpoints still work while the change is pending
    assert client.get("/users/me", headers=headers).status_code == 200
    assert client.get("/users/me/export", headers=headers).status_code == 200

    rotated = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "unblocked-99"},
        headers=headers,
    )
    assert rotated.status_code == 200
    new_headers = {"Authorization": f"Bearer {rotated.json()['access_token']}"}
    assert client.get("/admin/users", headers=new_headers).status_code == 200


def test_force_change_flag_follows_setting(tmp_path) -> None:
    # Secure-by-default: bootstrap admin gets a forced rotation even in dev.
    settings = Settings(
        env="development",
        database_url=f"sqlite:///{tmp_path}/dev.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
    )
    client = TestClient(create_app(settings))
    login = client.post("/auth/login", json={"email": "root@example.com", "password": PASSWORD})
    assert login.json()["must_change_password"] is True

    # Opt-out is explicit and honoured.
    settings = Settings(
        env="development",
        database_url=f"sqlite:///{tmp_path}/dev2.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    login = client.post("/auth/login", json={"email": "root@example.com", "password": PASSWORD})
    assert login.json()["must_change_password"] is False


def test_production_boot_guard_refuses_insecure_settings(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app(
            Settings(
                env="production",
                jwt_secret="short",
                admin_email="a@b.com",
                admin_password="longenoughpass1",
            )
        )
    with pytest.raises(RuntimeError, match="ADMIN_EMAIL"):
        create_app(Settings(env="production", jwt_secret="x" * 40))
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        create_app(
            Settings(
                env="production",
                jwt_secret="x" * 40,
                admin_email="a@b.com",
                admin_password="short12",
            )
        )
    with pytest.raises(RuntimeError, match="PII_ENC_KEY"):
        create_app(
            Settings(
                env="production",
                database_url=f"sqlite:///{tmp_path}/prod-guard-nokey.db",
                jwt_secret="x" * 40,
                admin_email="a@b.com",
                admin_password="longenoughpass1",
                allowed_origins="https://app.example.com",
            )
        )
    app = create_app(
        Settings(
            env="production",
            database_url=f"sqlite:///{tmp_path}/prod-guard.db",  # persistent (V8)
            jwt_secret="x" * 40,
            admin_email="a@b.com",
            admin_password="longenoughpass1",
            allowed_origins="https://app.example.com",  # CORS allowlist required in prod (S0.5)
            pii_enc_key=Fernet.generate_key().decode(),  # PII encryption required in prod (S5.6)
        )
    )
    assert app.title == "Bangla GPT API"


def test_rate_limit_backend_validation(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="RATE_LIMIT_BACKEND"):
        create_app(
            Settings(
                env="test",
                database_url=f"sqlite:///{tmp_path}/v.db",
                rate_limit_backend="memcached",
            )
        )
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        create_app(
            Settings(
                env="test", database_url=f"sqlite:///{tmp_path}/r.db", rate_limit_backend="redis"
            )
        )
