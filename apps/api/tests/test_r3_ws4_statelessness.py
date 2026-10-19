"""C-07: the single-instance exceptions are explicit, guarded and pinned.

`docs/security/statelessness.md` states the posture; this file pins the three
pieces of it that a future edit could silently undo:

1. the boot guard that refuses per-process rate-limit/cache backends once
   more than one worker runs (the compose defaults keep the guard
   satisfiable, so the shipped stack is not one env edit away from it);
2. the AiJob recovery loop is armed on EVERY backend -- in-process execution
   is the documented exception, and its safety rests on the atomic DB claim
   being reachable from any replica;
3. the document itself names the exception and the verify method, so the
   claim cannot rot out of the docs while the code changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import _validate_rate_limit_redis, create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "security" / "statelessness.md"
COMPOSE = REPO_ROOT / "docker-compose.yml"


def _prod(monkeypatch, **overrides) -> Settings:
    monkeypatch.setenv("WEB_CONCURRENCY", overrides.pop("workers", "2"))
    return Settings(env="production", **overrides)


def test_memory_rate_limit_is_refused_with_multiple_workers(monkeypatch) -> None:
    problems = _validate_rate_limit_redis(_prod(monkeypatch, rate_limit_backend="memory"))
    assert problems, "a per-process limiter with 2 workers must refuse to boot"
    assert "multiplied by the worker count" in problems[0]


def test_redis_backend_with_url_is_accepted(monkeypatch) -> None:
    assert not _validate_rate_limit_redis(
        _prod(monkeypatch, rate_limit_backend="redis", redis_url="redis://cache:6379/0")
    )


def test_compose_defaults_satisfy_the_guard() -> None:
    """The shipped stack must not ship the refused combination."""
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    env = compose["services"]["api"]["environment"]
    assert env["RATE_LIMIT_BACKEND"] == "${RATE_LIMIT_BACKEND:-redis}"
    assert env["WEB_CONCURRENCY"] == "${WEB_CONCURRENCY:-2}"
    assert env["REDIS_URL"], "redis backend without a URL is refused at boot"
    assert env["RATE_LIMIT_FAIL_OPEN"] == "${RATE_LIMIT_FAIL_OPEN:-false}"


@pytest.mark.parametrize("backend", ["inline", "arq"])
def test_ai_job_recovery_is_armed_on_every_backend(tmp_path, backend: str) -> None:
    """In-process AiJob execution is the documented exception.

    Its single-run guarantee is the atomic DB claim, so the recovery loop must
    run for BOTH scheduler shapes -- an `arq` deployment still needs a replica
    to pick up jobs abandoned by a killed process
    (`initialize/lifespan.py` says this in prose; this pins it).
    """
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/r3_ws4_stateless.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        jobs_backend=backend,
    )
    app = create_app(settings)
    with TestClient(app):
        assert app.state.ai_job_recovery_task is not None
        assert not app.state.ai_job_recovery_task.done()


def test_the_doc_names_the_exception_and_the_verify_method() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "IN-PROCESS" in text and "claim_ai_job" in text
    assert "replica_check.py" in text
    assert "test_h2_jobs_single_run.py" in text
    # The shared/per-process split is the point of the document; a stub would not carry it.
    assert "Shared state" in text and "Per-process state" in text
