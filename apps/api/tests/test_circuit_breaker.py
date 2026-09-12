"""Tests for the circuit breaker pattern and provider fallback router.

Verifies the Hystrix-style state machine:
- CLOSED -> OPEN (after failure_threshold consecutive failures)
- OPEN -> HALF_OPEN (after reset_timeout_seconds)
- HALF_OPEN -> CLOSED (on successful probe)
- HALF_OPEN -> OPEN (on failed probe)
- ProviderFallbackRouter switches to fallback when primary circuit opens
"""

import asyncio

import pytest

from bangla_gpt_api.providers.base import LLMProvider, ProviderError
from bangla_gpt_api.services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerMiddleware,
    CircuitOpenError,
    CircuitState,
    ProviderFallbackRouter,
)

# ── Mock provider for testing ────────────────────────────────────────────────


class FailingProvider(LLMProvider):
    """Provider that raises ProviderError every call."""

    name = "failing"

    def __init__(self, always_fail: bool = True) -> None:
        self.always_fail = always_fail
        self.call_count = 0

    async def generate(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> str:
        self.call_count += 1
        if self.always_fail:
            raise ProviderError("simulated failure")
        return "ok"

    def stream(self, prompt: str, *, system: str | None = None, image: dict | None = None):
        raise NotImplementedError


class SuccessfulProvider(LLMProvider):
    """Provider that always succeeds."""

    name = "successful"

    def __init__(self) -> None:
        self.call_count = 0

    async def generate(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> str:
        self.call_count += 1
        return "ok"

    def stream(self, prompt: str, *, system: str | None = None, image: dict | None = None):
        raise NotImplementedError


# ── CircuitBreaker basic operations ─────────────────────────────────────────


async def test_initial_state_is_closed() -> None:
    cb = CircuitBreaker(failure_threshold=3, name="test")
    assert cb.state == CircuitState.CLOSED


async def test_allows_request_when_closed() -> None:
    cb = CircuitBreaker(failure_threshold=3, name="test")
    assert cb.allow_request() is True


async def test_records_failure_and_opens_circuit() -> None:
    cb = CircuitBreaker(failure_threshold=3, name="test")
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


async def test_records_success_closes_circuit() -> None:
    cb = CircuitBreaker(failure_threshold=2, name="test")
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    # In HALF_OPEN, success closes the circuit
    # We need a short timeout to transition to HALF_OPEN
    await asyncio.sleep(0.15)  # timeout is 60s default so won't trigger; just verify clear
    # Success while OPEN clears failures but stays OPEN until timeout
    cb.record_success()
    # _record_success clears failures but only transitions CLOSED from HALF_OPEN
    # So OPEN stays OPEN — this is correct behavior
    assert cb.state == CircuitState.OPEN
    # After timeout → HALF_OPEN → success → CLOSED
    cb2 = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=0.1, name="test2")
    cb2.record_failure()
    cb2.record_failure()
    await asyncio.sleep(0.15)
    assert cb2.state == CircuitState.HALF_OPEN
    cb2.record_success()
    assert cb2.state == CircuitState.CLOSED


async def test_clears_failures_on_success() -> None:
    cb = CircuitBreaker(failure_threshold=3, name="test")
    cb.record_failure()
    cb.record_failure()
    cb.record_success()  # Clears all failures
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED  # Only 1 failure, needs 3


async def test_half_open_after_timeout() -> None:
    cb = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=0.1, name="test")
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    await asyncio.sleep(0.15)  # Wait for timeout
    assert cb.state == CircuitState.HALF_OPEN


async def test_half_open_reopens_on_failure() -> None:
    cb = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.1, name="test")
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    await asyncio.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN
    # A new failure in half-open should reopen
    cb.record_failure()
    assert cb.state == CircuitState.OPEN


async def test_half_open_closes_on_success() -> None:
    cb = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.1, name="test")
    cb.record_failure()
    await asyncio.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


async def test_only_one_probe_in_half_open() -> None:
    cb = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.1, name="test")
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    await asyncio.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN
    assert cb.allow_request() is True  # First probe allowed
    assert cb.allow_request() is False  # Second probe blocked


async def test_get_metrics() -> None:
    cb = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=60.0, name="my-cb")
    cb.record_failure()
    cb.record_failure()
    metrics = cb.get_metrics()
    assert metrics["name"] == "my-cb"
    assert metrics["state"] == "closed"
    assert metrics["failure_count"] == 2
    assert metrics["threshold"] == 3


# ── CircuitBreakerMiddleware ────────────────────────────────────────────────


async def test_middleware_allows_through_when_closed() -> None:
    cb = CircuitBreaker(failure_threshold=3, name="test")
    async with CircuitBreakerMiddleware(cb):
        pass  # Should not raise
    assert cb.state == CircuitState.CLOSED  # Success recorded


async def test_middleware_records_failure_on_exception() -> None:
    cb = CircuitBreaker(failure_threshold=2, name="test")
    with pytest.raises(ValueError):
        async with CircuitBreakerMiddleware(cb):
            raise ValueError("simulated error")
    assert cb.state == CircuitState.CLOSED  # One failure
    cb.record_failure()  # Second failure
    assert cb.state == CircuitState.OPEN


async def test_middleware_raises_when_circuit_open() -> None:
    cb = CircuitBreaker(failure_threshold=1, name="test")
    cb.record_failure()  # Opens circuit
    assert cb.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError, match="OPEN"):
        async with CircuitBreakerMiddleware(cb):
            pass  # Never reached


# ── ProviderFallbackRouter ──────────────────────────────────────────────────


async def test_router_starts_with_primary() -> None:
    primary = SuccessfulProvider()
    fallback = SuccessfulProvider()
    router = ProviderFallbackRouter(primary, fallback)
    assert router.active_provider_name == "successful"
    assert router.fallback_active is False


async def test_router_switches_to_fallback_when_primary_opens() -> None:
    primary = FailingProvider()
    fallback = SuccessfulProvider()
    cb = CircuitBreaker(failure_threshold=2, name="primary")
    router = ProviderFallbackRouter(primary, fallback, cb)

    # First failure via middleware (middleware auto-records failure)
    with pytest.raises(ProviderError):
        async with CircuitBreakerMiddleware(cb):
            await primary.generate("q")

    # Second failure via middleware (circuit opens)
    with pytest.raises(ProviderError):
        async with CircuitBreakerMiddleware(cb):
            await primary.generate("q")

    assert cb.state == CircuitState.OPEN
    # Router should now suggest fallback
    assert router.should_switch_to_fallback() is True
    selected = await router.select_provider("q")
    assert selected.name == "successful"
    assert router.fallback_active is True


async def test_router_switches_back_when_primary_recovers() -> None:
    primary = FailingProvider(always_fail=False)  # Actually succeeds
    fallback = SuccessfulProvider()
    cb = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=0.1, name="primary")
    router = ProviderFallbackRouter(primary, fallback, cb)

    # Simulate opening the circuit
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Switch to fallback
    selected = await router.select_provider("q")
    assert selected.name == "successful"
    assert router.fallback_active is True

    # Simulate timeout → HALF_OPEN, then successful probe
    await asyncio.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()  # Successful probe closes circuit
    assert cb.state == CircuitState.CLOSED

    # Router should switch back
    assert router.check_primary_health() is True
    assert router.should_switch_to_fallback() is False


async def test_router_no_fallback_configured() -> None:
    primary = FailingProvider()
    router = ProviderFallbackRouter(primary, None)
    assert router.should_switch_to_fallback() is False
    assert router.fallback_active is False


async def test_router_no_breaker_configured() -> None:
    primary = FailingProvider()
    fallback = SuccessfulProvider()
    router = ProviderFallbackRouter(primary, fallback, primary_breaker=None)
    assert router.should_switch_to_fallback() is False
    assert router.check_primary_health() is True


async def test_router_get_status() -> None:
    primary = SuccessfulProvider()
    fallback = SuccessfulProvider()
    cb = CircuitBreaker(failure_threshold=3, name="primary")
    router = ProviderFallbackRouter(primary, fallback, cb)
    status = router.get_status()
    assert status["primary"] == "successful"
    assert status["active"] == "successful"
    assert status["fallback_active"] is False
    assert "primary_breaker" in status


# ── Integration: Router + middleware together ────────────────────────────────


async def test_full_resilience_chain() -> None:
    """Simulate the full chain: router -> breaker -> provider.

    Real flow in ask()/ask_stream():
    1. Circuit times out → state becomes HALF_OPEN
    2. select_provider() uses the one allowed probe, returns fallback
    3. Fallback generates answer successfully
    4. router.record_result(True) calls cb.record_success()
       → HALF_OPEN + success → CLOSED → router switches back
    """
    failing_primary = FailingProvider()
    successful_fallback = SuccessfulProvider()
    cb = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=0.1, name="primary")
    router = ProviderFallbackRouter(failing_primary, successful_fallback, cb)

    # Phase 1: Primary works (it doesn't always fail)
    failing_primary.always_fail = False
    selected = await router.select_provider("q")
    assert selected.name == "failing"
    result = await selected.generate("q")
    assert result == "ok"
    router.record_result(True)
    assert cb.state == CircuitState.CLOSED

    # Phase 2: Primary starts failing — simulate 2 consecutive failures
    failing_primary.always_fail = True
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Phase 3: Router switches to fallback
    assert router.should_switch_to_fallback() is True
    selected = await router.select_provider("q")
    assert selected.name == "successful"
    assert router.fallback_active is True

    # Phase 4: Primary recovers
    failing_primary.always_fail = False
    await asyncio.sleep(0.15)  # timeout elapsed
    # Trigger state transition by reading cb.state (this is what the middleware does)
    assert cb.state == CircuitState.HALF_OPEN
    # Now record_result triggers record_success which sees HALF_OPEN → CLOSED
    router.record_result(True)
    assert cb.state == CircuitState.CLOSED
    assert router.fallback_active is False
    assert router.active_provider_name == "failing"


# ── App level: TutorService rides the breaker into the fallback ──────────────


async def test_tutor_service_falls_back_after_breaker_opens() -> None:
    """REL-001: end-to-end provider outage survival inside TutorService.

    failing primary (threshold 1) -> first ask raises ProviderError and trips
    the circuit -> second ask is served by the fallback provider.
    """
    from bangla_gpt_api.data.loader import load_sample_corpus
    from bangla_gpt_api.providers.base import ProviderError
    from bangla_gpt_api.retrieval.bm25 import BM25Index
    from bangla_gpt_api.services.tutor import TutorService

    primary = FailingProvider(always_fail=True)
    fallback = SuccessfulProvider()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=3600.0, name="t")
    svc = TutorService(
        index=BM25Index(load_sample_corpus()),
        provider=primary,
        circuit_breaker=breaker,
        fallback_provider=fallback,
    )
    with pytest.raises(ProviderError):
        await svc.ask("ভগ্নাংশ কী?", class_level=6, subject="mathematics")
    assert breaker.state == CircuitState.OPEN
    answer = await svc.ask("ভগ্নাংশ কী?", class_level=6, subject="mathematics")
    assert answer.answer == "ok"
    assert answer.grounded is True
