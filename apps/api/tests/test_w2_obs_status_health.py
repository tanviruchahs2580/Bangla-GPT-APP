"""F-123: /status must not claim the assistant is healthy during an outage.

The page used to report ``assistant_ok = provider is not None``, so a provider
pointed at a closed port answered ``/ready`` 200 while every ask returned 502.
These tests pin the replacement: the outcome of real provider calls (the signal
that exists whether or not a fallback chain is configured) plus the circuit
breaker when one is built.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.base import (
    PROVIDER_DEGRADED_AFTER,
    ProviderError,
    provider_health,
    reset_provider_health,
)
from bangla_gpt_api.providers.openai import OpenAIProvider
from bangla_gpt_api.services.circuit_breaker import CircuitBreaker
from conftest import engine_url

SECRET = "w2-obs-status-0123456789abcdef"


@pytest.fixture(autouse=True)
def _clean_provider_health():
    """The tracker is process state; keep tests independent of call order."""
    reset_provider_health()
    yield
    reset_provider_health()


@pytest.fixture
def app(tmp_path):
    return create_app(
        Settings(
            env="test",
            database_url=engine_url(tmp_path, "w2status"),
            jwt_secret=SECRET,
        )
    )


def _component(client: TestClient, name: str) -> dict:
    body = client.get("/status").json()
    return next(component for component in body["components"] if component["name"] == name)


def _failing_provider() -> OpenAIProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"error": {"code": 500, "message": "upstream down", "type": "server_error"}},
            request=request,
        )

    return OpenAIProvider(
        api_key="test-key",
        model="gpt-4o-mini",
        timeout_seconds=2.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )


async def test_consecutive_provider_failures_flip_the_status_component(app) -> None:
    client = TestClient(app)
    assert _component(client, "assistant")["ok"] is True

    provider = _failing_provider()
    for _ in range(PROVIDER_DEGRADED_AFTER):
        with pytest.raises(ProviderError):
            await provider.generate("প্রশ্ন")

    assistant = _component(client, "assistant")
    assert assistant["ok"] is False
    assert "consecutive provider calls failed" in assistant["detail"]
    assert client.get("/status").json()["status"] == "degraded"


async def test_a_successful_call_clears_the_failure_streak(app) -> None:
    provider = _failing_provider()
    for _ in range(PROVIDER_DEGRADED_AFTER):
        with pytest.raises(ProviderError):
            await provider.generate("প্রশ্ন")
    assert provider_health()[0] is False

    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "উত্তর"}}]},
            request=request,
        )

    healthy = OpenAIProvider(
        api_key="test-key",
        model="gpt-4o-mini",
        timeout_seconds=2.0,
        max_retries=0,
        transport=httpx.MockTransport(ok_handler),
    )
    assert await healthy.generate("প্রশ্ন") == "উত্তর"

    client = TestClient(app)
    assistant = _component(client, "assistant")
    assert assistant["ok"] is True
    assert assistant["detail"] == "last provider call succeeded"


def test_an_open_circuit_breaker_flips_the_status_component(app) -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=300.0, name="test")
    app.state.ctx.circuit_breaker = breaker
    client = TestClient(app)
    assert _component(client, "assistant")["ok"] is True

    breaker.record_failure()

    assistant = _component(client, "assistant")
    assert assistant["ok"] is False
    assert "circuit open" in assistant["detail"]
    assert client.get("/status").json()["status"] == "degraded"


def test_cache_detail_names_the_backend_that_answers(app) -> None:
    # The default test cache is the in-process one; its ping is unconditionally
    # true, so claiming a "shared cache" would describe a dependency that is
    # not there.
    cache = _component(TestClient(app), "cache")
    assert cache["ok"] is True
    assert cache["detail"] == "in-process cache active"
