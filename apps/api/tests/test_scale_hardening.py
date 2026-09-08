"""National-scale hardening tests.

Covers the improvements that keep the product correct and operable at
Bangladesh scale: env-template validity, privacy-safe event logging,
no orphan chat turns on LLM failure, proxy-aware rate-limit identities,
and a bounded in-memory limiter.
"""

import logging

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.ratelimit import MemoryRateLimiter
from bangla_gpt_api.services.tutor import TutorService

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/scale.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
        **overrides,
    )


def _student(client: TestClient) -> tuple[dict, int]:
    res = client.post(
        "/auth/register",
        json={
            "name": "Scale Probe",
            "email": "scale@example.com",
            "password": PASSWORD,
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert res.status_code == 201
    login = client.post("/auth/login", json={"email": "scale@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    conv = client.post("/tutor/conversations", json={}, headers=headers)
    assert conv.status_code == 201
    return headers, conv.json()["id"]


def test_env_example_values_boot_a_valid_settings(tmp_path) -> None:
    """The template every operator copies must parse into valid Settings."""
    from pathlib import Path

    example = Path(__file__).resolve().parents[3] / ".env.example"
    assert example.exists(), ".env.example missing from repo root"
    seen: dict[str, str] = {}
    for line in example.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        seen[key.strip()] = value.strip()
    # Values must be non-empty for settings that require one.
    assert seen.get("ALLOW_DIRECT_PARENT_LINK") in ("true", "false")
    assert seen.get("INVITE_TTL_MINUTES", "").isdigit()
    known = Settings.model_fields.keys()
    settings = Settings(env="development", **{k: v for k, v in seen.items() if k in known})  # type: ignore[arg-type]
    assert settings.invite_ttl_minutes > 0
    assert settings.allow_direct_parent_link is False


def test_events_log_props_keys_never_values(tmp_path) -> None:
    class _Capture(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    capture = _Capture()
    app_logger = logging.getLogger("bangla_gpt_api.main")
    old_level = app_logger.level
    app_logger.addHandler(capture)
    app_logger.setLevel(logging.INFO)  # pytest's plugin raises root to WARNING
    try:
        client = TestClient(create_app(_settings(tmp_path)))
        admin = client.post(
            "/auth/login", json={"email": "root@example.com", "password": PASSWORD}
        ).json()["access_token"]
        res = client.post(
            "/events",
            json={"name": "quiz_start", "props": {"student_phone": "01712345678"}},
            headers={"Authorization": f"Bearer {admin}"},
        )
    finally:
        app_logger.removeHandler(capture)
        app_logger.setLevel(old_level)

    assert res.status_code == 202
    import json as _json

    event_lines = [
        _json.loads(r.getMessage())
        for r in capture.records
        if r.getMessage().startswith("{") and "product_event" in r.getMessage()
    ]
    assert event_lines, "product_event log record expected"
    assert event_lines[0]["props_keys"] == ["student_phone"]
    # The phone number (prop VALUE) must never reach the log payload.
    assert all("01712345678" not in _json.dumps(e) for e in event_lines)


def test_chat_user_message_not_orphaned_on_llm_failure(tmp_path, monkeypatch) -> None:
    async def failing_ask(self, *args, **kwargs):  # noqa: ANN001, ANN002
        raise ProviderError("mocked provider outage")

    monkeypatch.setattr(TutorService, "ask", failing_ask)
    client = TestClient(create_app(_settings(tmp_path)))
    headers, conv_id = _student(client)

    res = client.post(
        f"/tutor/conversations/{conv_id}/messages",
        json={"message": "কোষ কী?", "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 502

    history = client.get(f"/tutor/conversations/{conv_id}/messages", headers=headers).json()
    assert history == [], "failed LLM turn must not persist the user message"


def test_stream_user_message_not_orphaned_on_llm_failure(tmp_path, monkeypatch) -> None:
    async def failing_stream(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise ProviderError("mocked provider outage")
        yield ""  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(TutorService, "ask_stream", failing_stream)
    client = TestClient(create_app(_settings(tmp_path)))
    headers, conv_id = _student(client)

    with client.stream(
        "POST",
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={"message": "কোষ কী?", "subject": "science"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "event: error" in body

    history = client.get(f"/tutor/conversations/{conv_id}/messages", headers=headers).json()
    assert history == [], "failed stream turn must not persist the user message"


def test_proxy_header_rate_limit_identity(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path, trust_proxy_headers=True)))
    spoofed = {"X-Forwarded-For": "203.0.113.7"}
    # Login limiter: 10/min per IP. 10 attempts exhaust IP .7's budget.
    codes = {
        client.post(
            "/auth/login",
            json={"email": f"u{i}@x.com", "password": "wrongpass1"},
            headers=spoofed,
        ).status_code
        for i in range(10)
    }
    assert codes == {401}
    blocked = client.post(
        "/auth/login",
        json={"email": "u@x.com", "password": "wrongpass1"},
        headers=spoofed,
    )
    assert blocked.status_code == 429
    # A different forwarded client still has its own budget.
    other = client.post(
        "/auth/login",
        json={"email": "u@x.com", "password": "wrongpass1"},
        headers={"X-Forwarded-For": "198.51.100.9"},
    )
    assert other.status_code == 401


def test_memory_limiter_key_space_is_bounded() -> None:
    limiter = MemoryRateLimiter(max_keys=50)
    for i in range(500):
        assert limiter.check(f"key-{i}", 10)
    assert len(limiter._hits) <= 50
    # A brand-new key is still serviceable after eviction churn.
    assert limiter.check("key-fresh", 10)
