"""C-15: contract tests for the email and queue seams.

Companion to ``test_c2_seam_provider_index.py`` (the LLM and index seams).
Both halves of this file pin a *boundary* rather than an implementation:

* the email seam's documented ``False``-not-raise verdict, its message shape,
  the keyword-only call convention every caller and the retrying wrapper rely
  on, and the configured-triple rule;
* the queue seam: the ARQ worker is wiring only, one job body per entry point
  in ``jobs.py``, every body is at-most-once per period from either scheduler,
  and the worker owns its own database session.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import smtplib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from bangla_gpt_api import jobs
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.services import mailer

APP = Path(__file__).resolve().parents[1]
SECRET = "test-secret-0123456789abcdef0123456789"


# =========================================================================== #
# 3. Email seam


class _FakeSmtp:
    """A tiny SMTP stand-in: records what was sent, or fails as told."""

    instances: ClassVar[list[_FakeSmtp]] = []
    fail_with: ClassVar[type[Exception] | None] = None

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.sent: list[Any] = []
        self.logged_in: tuple[str, str] | None = None
        _FakeSmtp.instances.append(self)

    def __enter__(self) -> _FakeSmtp:
        if _FakeSmtp.fail_with is not None:
            raise _FakeSmtp.fail_with("relay down")
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self, context: Any) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, message: Any) -> None:
        self.sent.append(message)


@pytest.fixture
def smtp(monkeypatch):
    _FakeSmtp.instances = []
    _FakeSmtp.fail_with = None
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtp)
    return _FakeSmtp


def _mail_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "jwt_secret": SECRET,
        "smtp_enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_from": "bot@example.com",
        "smtp_user": "bot",
        "smtp_password": "pw",
        "smtp_port": 2525,
    }
    values.update(overrides)
    return Settings(**values)


def test_email_seam_is_configured_only_with_the_full_triple() -> None:
    assert mailer.smtp_configured(_mail_settings()) is True
    assert mailer.smtp_configured(Settings(env="test", jwt_secret=SECRET)) is False
    assert mailer.smtp_configured(_mail_settings(smtp_host=None)) is False
    assert mailer.smtp_configured(_mail_settings(smtp_from=None)) is False


def test_email_seam_sends_with_the_documented_message_shape(smtp) -> None:
    assert (
        mailer.send_mail(_mail_settings(), to="p@example.com", subject="বিষয়", body="দেহ") is True
    )
    instance = smtp.instances[-1]
    assert (instance.host, instance.port, instance.timeout) == ("smtp.example.com", 2525, 15)
    assert instance.logged_in == ("bot", "pw")
    message = instance.sent[-1]
    assert message["From"] == "bot@example.com"
    assert message["To"] == "p@example.com"
    assert message["Subject"] == "বিষয়"
    assert "দেহ" in message.get_content()


@pytest.mark.parametrize("failure", [OSError, smtplib.SMTPException])
def test_email_seam_reports_transport_failure_as_false(smtp, failure) -> None:
    """The contract every caller (and the retrying wrapper) depends on."""
    smtp.fail_with = failure
    assert mailer.send_mail(_mail_settings(), to="p@example.com", subject="s", body="b") is False


def test_email_seam_is_keyword_only_after_settings() -> None:
    for fn in (mailer.send_mail, jobs.send_mail_with_retry):
        signature = inspect.signature(fn)
        parameters = list(signature.parameters.values())
        assert parameters[0].name in {"settings", "cfg"}
        for parameter in parameters[1:]:
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (fn.__name__, parameter.name)
    assert set(inspect.signature(mailer.send_mail).parameters) >= {"to", "subject", "body"}


def test_email_seam_returns_false_when_unconfigured() -> None:
    assert (
        mailer.send_mail(Settings(env="test", jwt_secret=SECRET), to="a@b.c", subject="s", body="b")
        is False
    )


# =========================================================================== #
# 4. Queue seam


def _worker_module() -> Any:
    spec = importlib.util.spec_from_file_location("bgpt_worker_c15", APP / "worker.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_queue_seam_is_wiring_only_over_jobs_py() -> None:
    """Every ARQ job body delegates to a jobs.py entry point (one core)."""
    worker = _worker_module()
    expected = {
        "job_weekly_digest": "run_weekly_digest",
        "job_nightly_rollup": "run_nightly_rollup",
        "job_retention_sweep": "run_retention_job",
    }
    assert {f.__name__ for f in worker.WorkerSettings.functions} == set(expected)
    for wrapper_name, body_name in expected.items():
        wrapper = getattr(worker, wrapper_name)
        source = inspect.getsource(wrapper)
        assert f"jobs.{body_name}" in source, f"{wrapper_name} must delegate to jobs.{body_name}"
        assert callable(getattr(jobs, body_name))


def test_queue_seam_worker_builds_its_own_session(monkeypatch) -> None:
    """The worker owns its DB session; it never borrows the web process's."""
    worker = _worker_module()
    built: dict[str, Any] = {}

    def fake_settings():
        built["settings"] = Settings(env="test", jwt_secret=SECRET)
        return built["settings"]

    def fake_make_engine(settings):
        built["engine_called"] = settings
        return "engine"

    def fake_factory(engine):
        built["factory_engine"] = engine
        return "factory"

    monkeypatch.setattr(worker, "get_settings", fake_settings)
    monkeypatch.setattr(worker, "make_engine", fake_make_engine)
    monkeypatch.setattr(worker, "make_session_factory", fake_factory)
    ctx: dict[str, Any] = {}
    asyncio.run(worker.startup(ctx))
    assert ctx["settings"] is built["settings"]
    assert ctx["session_factory"] == "factory" and built["factory_engine"] == "engine"


def _job_factory(tmp_path: Path):
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/queue.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password="supersecret1",
        force_admin_password_change=False,
    )
    engine = make_engine(settings)
    init_db(engine)
    return make_session_factory(engine), settings, engine, tmp_path / "queue.db"


def test_queue_seam_every_body_is_at_most_once_per_period(tmp_path) -> None:
    """One contract, applied to all three queue bodies.

    Whether the inline loop calls a body or the ARQ cron does, the second call
    for the same period must be a no-op -- that property is what makes two
    schedulers safe to run side by side.
    """
    make_session, settings, engine, db_path = _job_factory(tmp_path)
    sent: list[str] = []

    def sender(_settings, *, to, subject, body):  # noqa: ANN001, ANN202 - mirrors send_mail
        sent.append(to)
        return True

    try:
        rollup_now = datetime(2026, 9, 6, 21, 30)
        assert jobs.run_nightly_rollup(make_session, settings, now=rollup_now)["ran"] is True
        second = jobs.run_nightly_rollup(make_session, settings, now=rollup_now)
        assert second == {"ran": False, "reason": "already_ran", "period": "2026-09-06"}

        retention_now = datetime(2026, 9, 6, 21, 30)
        assert jobs.run_retention_job(make_session, settings, now=retention_now)["ran"] is True
        assert jobs.run_retention_job(make_session, settings, now=retention_now)["ran"] is False

        digest_now = datetime(2026, 9, 6, 16, 30)
        first = jobs.run_weekly_digest(make_session, settings, now=digest_now, sender=sender)
        assert first["ran"] is True
        assert jobs.run_weekly_digest(make_session, settings, now=digest_now, sender=sender) == {
            "ran": False,
            "reason": "already_ran",
            "period": first["period"],
        }

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT job, period_key, outcome FROM job_runs ORDER BY job"
            ).fetchall()
        finally:
            conn.close()
        assert [r[0] for r in rows] == ["nightly_rollup", "parent_digest", "retention_sweep"]
        assert all(r[2] is not None for r in rows), "every claimed period records its outcome"
    finally:
        engine.dispose()


def test_queue_seam_body_signatures_are_stable() -> None:
    """Both schedulers call the bodies positionally: (session_factory, settings)."""
    for body in (jobs.run_weekly_digest, jobs.run_nightly_rollup, jobs.run_retention_job):
        signature = inspect.signature(body)
        parameters = list(signature.parameters.values())
        assert [p.name for p in parameters[:2]] == ["session_factory", "settings"]
        assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert parameters[1].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert signature.parameters["now"].kind is inspect.Parameter.KEYWORD_ONLY


def test_queue_seam_exposes_all_three_bodies_in_one_module() -> None:
    """One core, two schedulers: no job body may live in worker.py."""
    worker = _worker_module()
    for name in ("run_weekly_digest", "run_nightly_rollup", "run_retention_job"):
        assert not hasattr(worker, name), f"{name} belongs in jobs.py, not the worker wiring"
    assert jobs.__name__ == "bangla_gpt_api.jobs"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
