from collections.abc import AsyncIterator
from typing import Protocol

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
