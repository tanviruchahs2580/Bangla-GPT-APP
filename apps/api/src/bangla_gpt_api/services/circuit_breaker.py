"""Circuit breaker pattern for AI provider resilience.

Implements the classic circuit breaker pattern (Hystrix-style) with three
states:
- CLOSED: normal operation, requests pass through
- OPEN: circuit is tripped, requests are rejected immediately without
  calling the downstream provider
- HALF_OPEN: after reset_timeout seconds, a probe request is allowed
  through to test if the provider has recovered

When failures exceed the threshold within a sliding window, the circuit
opens. After the reset timeout, a single probe request determines whether
to close or reopen the circuit.

This protects the application from cascading failures when an LLM provider
is down or responding with errors.
"""

import enum
import logging
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bangla_gpt_api.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a request is made to an open circuit."""


class CircuitBreaker:
    """Thread-safe circuit breaker with sliding failure window.

    Args:
        failure_threshold: Number of consecutive failures before opening.
        reset_timeout_seconds: Seconds to wait before transitioning to
            half-open and allowing a probe request.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout_seconds: float = 60.0,
        name: str = "default",
    ) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout_seconds
        self._name = name
        self._state = CircuitState.CLOSED
        self._last_failure_time: float | None = None
        self._failure_timestamps: deque[float] = deque()
        self._half_open_probe: bool = False
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state, with automatic timeout check."""
        with self._lock:
            if self._state == CircuitState.OPEN and self._last_failure_time:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self._reset_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_probe = False
                    logger.info(
                        "circuit_breaker: [%s] transitioning to HALF_OPEN after %0.1fs timeout",
                        self._name,
                        elapsed,
                    )
            return self._state

    @property
    def name(self) -> str:
        return self._name

    def _record_failure(self) -> None:
        """Record a failure and check if threshold is exceeded."""
        now = time.monotonic()
        with self._lock:
            self._failure_timestamps.append(now)
            self._last_failure_time = now
            # Clean old failures outside the sliding window (keep last 60s)
            cutoff = now - 60.0
            while self._failure_timestamps and self._failure_timestamps[0] < cutoff:
                self._failure_timestamps.popleft()

            consecutive_failures = len(self._failure_timestamps)
            if consecutive_failures >= self._failure_threshold:
                if self._state != CircuitState.OPEN:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        "circuit_breaker: [%s] OPEN after %d failures in sliding window",
                        self._name,
                        consecutive_failures,
                    )

    def _record_success(self) -> None:
        """Record a success and reset the circuit."""
        with self._lock:
            self._failure_timestamps.clear()
            self._last_failure_time = None
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._half_open_probe = False
                logger.info("circuit_breaker: [%s] CLOSED after successful probe", self._name)
            elif self._state == CircuitState.CLOSED:
                logger.debug("circuit_breaker: [%s] success, circuit stays CLOSED", self._name)

    def allow_request(self) -> bool:
        """Check if a request should be allowed through.

        Returns:
            True if the request is allowed, False if the circuit is open.

        Raises:
            CircuitOpenError: if the circuit is OPEN and no probe is allowed.
        """
        current_state = self.state  # Triggers timeout check

        if current_state == CircuitState.CLOSED:
            return True
        if current_state == CircuitState.HALF_OPEN:
            # Only one probe request allowed at a time
            with self._lock:
                if not self._half_open_probe:
                    self._half_open_probe = True
                    return True
            return False
        # OPEN
        return False

    def record_failure(self) -> None:
        """Record a call failure."""
        self._record_failure()

    def record_success(self) -> None:
        """Record a call success."""
        self._record_success()

    def get_metrics(self) -> dict:
        """Return current breaker metrics for observability."""
        with self._lock:
            return {
                "name": self._name,
                "state": self._state.value,
                "failure_count": len(self._failure_timestamps),
                "last_failure_time": self._last_failure_time,
                "threshold": self._failure_threshold,
                "reset_timeout": self._reset_timeout,
            }


class CircuitBreakerMiddleware:
    """Async context manager that wraps AI calls with circuit breaker logic.

    Usage:
        async with CircuitBreakerMiddleware(breaker):
            result = await provider.generate(prompt)
        # If the circuit is open, a CircuitOpenError is raised instead.
    """

    def __init__(self, breaker: CircuitBreaker) -> None:
        self._breaker = breaker

    async def __aenter__(self) -> "CircuitBreakerMiddleware":
        if not self._breaker.allow_request():
            metrics = self._breaker.get_metrics()
            raise CircuitOpenError(
                f"Circuit breaker [{self._breaker.name}] is OPEN "
                f"(failures={metrics['failure_count']}, state={metrics['state']})"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
        return False  # Don't suppress exceptions


class ProviderFallbackRouter:
    """Routes AI calls between primary and fallback providers with circuit breaking.

    When the primary provider's circuit breaker opens (after repeated failures),
    this router automatically switches to the fallback provider. When the primary
    recovers, it switches back.
    """

    def __init__(
        self,
        primary: "LLMProvider",  # Avoid circular import
        fallback: "LLMProvider | None",
        primary_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._primary_breaker = primary_breaker
        self._active_provider: LLMProvider = primary
        self._fallback_active = False

    @property
    def active_provider_name(self) -> str:
        return self._active_provider.name

    @property
    def fallback_active(self) -> bool:
        return self._fallback_active

    def check_primary_health(self) -> bool:
        """Check if the primary circuit breaker allows requests."""
        if self._primary_breaker is None:
            return True
        return self._primary_breaker.allow_request()

    def should_switch_to_fallback(self) -> bool:
        """Decide whether to switch to the fallback provider.

        True when primary circuit is OPEN.
        """
        if self._primary_breaker is None:
            return False
        if self._fallback is None:
            return False
        return not self.check_primary_health()

    async def select_provider(
        self,
        prompt: str,
        *,
        system: str | None = None,
        image: dict | None = None,
    ) -> "LLMProvider":
        """Select the appropriate provider for this call.

        Falls back to the secondary provider if the primary circuit is open.
        Falls back to the primary as a last resort if no fallback is configured.
        """
        if self.should_switch_to_fallback():
            fallback = self._fallback
            if fallback is None:  # Unreachable per should_switch_to_fallback; stay primary.
                return self._active_provider
            self._active_provider = fallback
            self._fallback_active = True
            logger.warning(
                "circuit_breaker: switched to FALLBACK provider [%s]",
                self._active_provider.name,
            )
            return self._active_provider
        self._fallback_active = False
        return self._active_provider

    def record_result(self, success: bool) -> None:
        """Record the result and potentially switch back to primary."""
        if self._primary_breaker is not None:
            if success:
                self._primary_breaker.record_success()
            else:
                self._primary_breaker.record_failure()
        # If primary has recovered, switch back
        if self._fallback_active and self.check_primary_health():
            self._active_provider = self._primary
            self._fallback_active = False
            logger.info(
                "circuit_breaker: switched BACK to PRIMARY provider [%s]",
                self._active_provider.name,
            )

    def get_status(self) -> dict:
        """Return current router status."""
        status: dict = {
            "primary": self._primary.name,
            "active": self._active_provider.name,
            "fallback_active": self._fallback_active,
        }
        if self._primary_breaker:
            status["primary_breaker"] = self._primary_breaker.get_metrics()
        return status
