import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

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

#: Full-jitter retry policy (AWS "Exponential Backoff and Jitter", the
#: decorrelated variant): every delay is drawn uniformly from
#: ``[delay/2, delay]`` for the deterministic exponential ``0.5 * 2**n``,
#: capped at MAX_BACKOFF_SECONDS. Jitter is what stops a fleet of replicas
#: that all saw the same 503 from retrying in lockstep and re-creating the
#: overload (thundering herd); it is applied to the idempotent provider
#: calls only -- the policy is retry-on-transport/429/5xx, and a stream that
#: has already emitted tokens is never replayed.
JITTER_FLOOR = 0.5

#: The retry policy in one string, so an operator reading a metric or an
#: incident note can name it exactly.
RETRY_POLICY = "full-jitter [ceiling/2, ceiling], ceiling = min(0.5*2^n, 4s)"

#: SystemRandom: the jitter must not correlate with any seeded application
#: RNG (a seeded generator would make a retry storm deterministic again, which
#: is the failure mode jitter exists to break).
_JITTER_RNG = random.SystemRandom()


def retry_delay_seconds(attempt: int) -> float:
    """One retry delay for ``attempt`` (0-based) with full jitter.

    Bounded by the same ceiling as :func:`backoff_total_seconds`, so the
    fitted timeout budget stays valid: jitter can only make the chain
    shorter, never longer.
    """
    ceiling = min(0.5 * (2 ** max(0, attempt)), MAX_BACKOFF_SECONDS)
    return _JITTER_RNG.uniform(ceiling * JITTER_FLOOR, ceiling)


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


#: Per-stage wall-clock ceilings (A6-06/AUD-A2-08). These are fault ceilings,
#: not performance targets: retrieval at p95 ~250ms and a full answer at p95
#: <=12s are the budgets the load tests measure. A stage that trips its
#: ceiling is logged and degrades (retrieval -> abstain, generation ->
#: ProviderError) instead of holding the worker past its own timeout.
STAGE_TIMEOUT_SECONDS: dict[str, float] = {
    "retrieval": 5.0,
    "context": 2.0,
    # the whole provider chain (attempts + backoff), same budget fit_timeout uses
    "generation": LLM_TOTAL_BUDGET_SECONDS,
}


def stage_timeout_seconds(stage: str) -> float:
    """Ceiling for one pipeline stage (KeyError on an unknown stage name)."""
    return STAGE_TIMEOUT_SECONDS[stage]


@dataclass(frozen=True)
class SamplingParams:
    """Vendor-neutral sampling controls for one task (A6-06/AUD-A2-08).

    ``seed`` is sent where the provider supports it (Gemini
    ``generationConfig.seed``, OpenAI ``seed``); providers that do not support
    a field simply do not emit it. Idempotent retries reuse the same params,
    so a retry cannot change the answer's sampling regime.
    """

    temperature: float
    top_p: float | None = None
    seed: int | None = None

    def fields(self) -> dict[str, float | int]:
        payload: dict[str, float | int] = {"temperature": self.temperature}
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.seed is not None:
            payload["seed"] = self.seed
        return payload


#: Per-task determinism profile (A6-06). Grounded tutoring and structured
#: generation are low-temperature with a fixed seed: the same question against
#: the same evidence should not drift between two identical calls. There is no
#: "creative" task in this product.
TASK_SAMPLING: dict[str, SamplingParams] = {
    "tutor_answer": SamplingParams(temperature=0.2, top_p=0.9, seed=20261019),
    "tutor_stream": SamplingParams(temperature=0.2, top_p=0.9, seed=20261019),
    "generation": SamplingParams(temperature=0.2, top_p=0.95, seed=20261019),
    "default": SamplingParams(temperature=0.3, top_p=0.95),
}


def sampling_for(task: str) -> SamplingParams:
    """Sampling profile for a task name (falls back to ``default``)."""
    return TASK_SAMPLING.get(task, TASK_SAMPLING["default"])


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
    # Determinism contract (A6-06): providers that accept the ``sampling``
    # keyword and put its fields into their request declare it, so a caller
    # never passes sampling to a third-party/test provider that would raise
    # TypeError. Providers that declare it honour the fields their vendor
    # documents (see each provider's ``supports_seed``).
    supports_sampling: bool

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        image: dict | None = None,
        sampling: SamplingParams | None = None,
    ) -> str: ...

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        image: dict | None = None,
        sampling: SamplingParams | None = None,
    ) -> AsyncIterator[str]: ...


def sampling_kwargs(provider: object, task: str) -> dict[str, Any]:
    """``{"sampling": ...}`` for providers that declare support, else ``{}``.

    ``Any``-valued on purpose: callers spread it into a Protocol method whose
    keyword is typed, and mypy cannot check a heterogeneous ``**`` spread.
    """
    if not getattr(provider, "supports_sampling", False):
        return {}
    return {"sampling": sampling_for(task)}


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
