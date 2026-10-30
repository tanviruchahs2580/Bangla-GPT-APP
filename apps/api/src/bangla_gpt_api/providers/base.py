import functools
import inspect
import logging
import secrets
import threading
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol

from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.metrics import PROVIDER_LATENCY_SECONDS

logger = logging.getLogger(__name__)

#: Mirrors ``gunicorn --timeout`` in the container CMD (Dockerfile). A worker
#: that has not answered by then is SIGKILLed and every request it was serving
#: dies with it.
WORKER_TIMEOUT_SECONDS = 60.0

#: Total wall clock the whole retry chain may consume. The remaining 15s of
#: the worker timeout is for routing, auth, the database round trip and
#: writing the response.
LLM_TOTAL_BUDGET_SECONDS = 45.0

#: The backoff ceiling used by both real providers.
MAX_BACKOFF_SECONDS = 4.0


def backoff_total_seconds(max_retries: int) -> float:
    """Total sleep across a full retry chain (``min(0.5 * 2**n, 4)``).

    Computed by doubling a capped accumulator rather than ``2 ** n``: with a
    large ``LLM_MAX_RETRIES`` the power overflows a float long before the sum
    stops growing, which turned an arithmetic helper into a crash inside the
    provider constructor.
    """
    total = 0.0
    delay = 0.5
    for _ in range(max(0, max_retries)):
        total += min(delay, MAX_BACKOFF_SECONDS)
        delay = min(delay * 2, MAX_BACKOFF_SECONDS)
    return total


#: Jitter source for retry delays. SystemRandom rather than the module-level
#: ``random`` functions: the value only needs to decorrelate workers, but the
#: project's bandit ruleset (S311) treats the plain generator as a finding in
#: src, and a suppression would have to be justified for every call site.
_JITTER = secrets.SystemRandom()


def backoff_delay_seconds(attempt: int) -> float:
    """One retry delay, jittered (F-075).

    The pre-jitter schedule was ``min(0.5 * 2**attempt, 4)`` at eight call
    sites, so every worker that saw the same upstream blip retried on the same
    second - a thundering herd against a provider that is already failing. The
    delay stays inside the same envelope (never longer than the old schedule,
    at least half of it), so timeout budgets are unaffected.
    """
    base = min(0.5 * (2**attempt), MAX_BACKOFF_SECONDS)
    return base * _JITTER.uniform(0.5, 1.0)


def finish_stream(
    *,
    name: str,
    event: str,
    model: str,
    prompt_chars: int,
    answer_chars: int,
    chunks: int,
    started: float,
    attempt: int,
    extra_fields: Mapping[str, object] | None = None,
) -> None:
    """Close out a provider stream: refuse an empty one, record latency + log.

    Shared by the two SSE providers (F-072): the 12-line tail was copied
    between them, so a metric or log field added to one silently diverged from
    the other. Called after the stream's deltas have been yielded.
    """
    if not chunks:
        raise ProviderError(f"{name} stream produced no text")
    latency_ms = int((time.perf_counter() - started) * 1000)
    PROVIDER_LATENCY_SECONDS.labels(provider=name.lower()).observe(latency_ms / 1000)
    json_log(
        logger,
        logging.INFO,
        event,
        model=model,
        latency_ms=latency_ms,
        prompt_chars=prompt_chars,
        answer_chars=answer_chars,
        chunks=chunks,
        retries=attempt,
        **dict(extra_fields or {}),
    )


def worst_case_seconds(timeout_seconds: float, max_retries: int) -> float:
    """Upper bound on one provider call: every attempt times out."""
    attempts = max(1, max_retries + 1)
    return attempts * float(timeout_seconds) + backoff_total_seconds(max_retries)


def fit_timeout(
    timeout_seconds: float,
    max_retries: int,
    *,
    budget: float = LLM_TOTAL_BUDGET_SECONDS,
) -> float:
    """Per-attempt timeout that keeps the whole chain inside ``budget``.

    ``LLM_TIMEOUT_SECONDS`` (30) and ``LLM_MAX_RETRIES`` (2) are independent
    knobs, so the naive product is 30 x 3 + backoff = 91.5s — comfortably past
    the 60s worker timeout. A hung provider therefore does not produce a slow
    error page; it gets the worker SIGKILLed, taking every other request that
    worker was serving with it, and the client sees a dropped connection with
    no error code at all.

    Shrinking the per-attempt timeout keeps the operator's retry *count*
    (the thing they tune on evidence) and makes the timeout fit the budget.
    """
    attempts = max(1, max_retries + 1)
    usable = budget - backoff_total_seconds(max_retries)
    return max(1.0, min(float(timeout_seconds), usable / attempts))


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderError(RuntimeError):
    """Upstream LLM failed after applying timeout/retry policy."""


# ---------------------------------------------------------------------------
# Provider health for the public status page (F-123)
# ---------------------------------------------------------------------------
# /status reported the assistant as healthy whenever a provider OBJECT existed,
# so a total provider outage read "all ok" while every ask returned 502 (the
# audit reproduced it against a provider pointed at a closed port). The circuit
# breaker is only built when a fallback provider is configured, which the
# production template does not set, so the signal that always exists is the
# outcome of the calls themselves.

#: Consecutive failed provider calls before /status reports the assistant as
#: degraded. Matches the default circuit-breaker threshold so a single blip
#: never flips the page and the two signals agree.
PROVIDER_DEGRADED_AFTER = 3

_health_lock = threading.Lock()
_consecutive_failures = 0
_successes = 0


def note_provider_success() -> None:
    """Record one provider call that produced an answer."""
    global _consecutive_failures, _successes
    with _health_lock:
        _consecutive_failures = 0
        _successes += 1


def note_provider_failure() -> None:
    """Record one provider call that failed after the retry policy."""
    global _consecutive_failures
    with _health_lock:
        _consecutive_failures += 1


def reset_provider_health() -> None:
    """Clear the tracker (tests that drive providers in-process)."""
    global _consecutive_failures, _successes
    with _health_lock:
        _consecutive_failures = 0
        _successes = 0


def provider_health() -> tuple[bool, str]:
    """``(ok, detail)`` for the status page, from real call outcomes.

    ``ok`` is False only after ``PROVIDER_DEGRADED_AFTER`` consecutive
    failures: a provider that has never been called (fresh boot, or an idle
    worker) is not evidence of an outage, and neither is one slow failure.
    """
    with _health_lock:
        failures = _consecutive_failures
        called = _successes > 0
    if failures >= PROVIDER_DEGRADED_AFTER:
        return False, f"{failures} consecutive provider calls failed"
    if called:
        return True, "last provider call succeeded"
    return True, "provider configured"


def track_provider_health(method: Any) -> Any:
    """Record the outcome of one provider call for :func:`provider_health`.

    Applied to the providers' public ``generate`` and ``stream`` methods, so
    the counter tracks user-visible calls (after the retry policy) rather than
    individual HTTP attempts. An abandoned stream is neither a success nor a
    failure - the generator is closed without either branch running.
    """
    if inspect.isasyncgenfunction(method):

        @functools.wraps(method)
        async def stream_wrapper(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
            try:
                async for item in method(*args, **kwargs):
                    yield item
            except ProviderError:
                note_provider_failure()
                raise
            else:
                note_provider_success()

        return stream_wrapper

    @functools.wraps(method)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = await method(*args, **kwargs)
        except ProviderError:
            note_provider_failure()
            raise
        note_provider_success()
        return result

    return wrapper


class LLMProvider(Protocol):
    name: str
    # Vision-honesty contract (A10): providers that cannot see images must
    # declare it, so chat routes refuse image turns up front instead of the
    # provider silently answering text-only as if the picture was read.
    supports_vision: bool

    async def generate(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> str: ...

    def stream(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> AsyncIterator[str]: ...


class ProviderSettings(Protocol):
    """Minimal settings surface consumed by provider builders.

    Both the real:class:`Settings` and the lightweight fallback adapter
    satisfy this structurally, so mypy can verify the fallback chain
    without coupling providers to the full application config.
    """

    llm_provider: str
    gemini_api_key: str | None
    gemini_model: str
    openai_api_key: str | None
    openai_model: str
    openai_base_url: str | None
    llm_timeout_seconds: float
    llm_max_retries: int
    llm_max_output_tokens: int
