"""A8-05: the live-run recorder -- budget guard, pacing, recording, resume.

Extracted from ``scripts/evaluate_live.py`` so the guard that bounds a live
run's spend is unit-testable and the CLI stays a thin orchestrator. The
recordings this produces are what ``scripts/evaluate_replay.py`` replays in
CI, keyed by :func:`bangla_gpt_api.providers.replay.digest`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bangla_gpt_api.providers.base import LLMProvider, ProviderError
from bangla_gpt_api.providers.replay import digest as prompt_digest
from bangla_gpt_api.services.costs import estimate_tokens

logger = logging.getLogger("bangla_gpt_api.evaluation.live_recorder")

#: Vendor list prices per 1K tokens, read from
#: https://ai.google.dev/gemini-api/docs/pricing (page last updated 2026-10-16,
#: read 2026-10-19) -- the same source `services/costs.py` cites. Keep this
#: local to the evaluation tool: it exists to bound *this run's* spend, and
#: product budgeting stays in `services/costs.py`.
PRICES_USD_PER_1K: dict[str, tuple[float, float]] = {
    "gemini-3.1-flash-lite": (0.00025, 0.0015),
    "gemini-3.5-flash-lite": (0.00030, 0.0025),
}
PRICES_READ_ON = "2026-10-19"


class SpendCapExceeded(RuntimeError):
    """Raised before a call that would push the run past --max-usd."""


class QuotaExhausted(RuntimeError):
    """The provider refused for quota reasons after every retry.

    Distinct from a transient failure: a per-day cap cannot be waited out, so
    the run stops and the artifacts say so instead of looping for hours.
    """


class BudgetedRecordingProvider:
    """Wraps the real provider: budget guard + response recording + counters.

    Implements the :class:`LLMProvider` protocol by delegation, so the tutor
    code path is exactly the production one.

    Two robustness properties matter for a run that takes minutes over a
    school-grade connection and must not restart from zero:

    * **Resume**: responses already recorded (``resume``) are served without a
      network call, so an interrupted run continues where it stopped and
      re-spends nothing.
    * **Transient-failure retry**: DNS blips, timeouts and 5xx are retried with
      backoff here, because the alternative is losing the whole run. A failure
      that survives the retries still raises -- it is never recorded as an
      answer.
    """

    #: Attempts per call (1 initial + retries) and the base backoff.
    MAX_ATTEMPTS = 6
    BACKOFF_SECONDS = 1.5

    def __init__(
        self,
        inner: LLMProvider,
        *,
        model: str,
        max_usd: float,
        resume: list[dict[str, Any]] | None = None,
        min_interval: float = 0.0,
        sink_path: Path | None = None,
    ) -> None:
        self._inner = inner
        self.name = inner.name
        self.supports_vision = inner.supports_vision
        self.supports_sampling = inner.supports_sampling
        self.model = model
        self.max_usd = max_usd
        self.calls = 0
        self.resumed = 0
        self.retries = 0
        self.min_interval = min_interval
        self._last_call_at = 0.0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.spent_usd = 0.0
        self.errors: list[dict[str, str]] = []
        self.records: list[dict[str, Any]] = list(resume or [])
        self._by_digest = {rec["digest"]: rec for rec in self.records}
        # Append-as-we-go: a crash or a quota stop must not cost the answers
        # already paid for -- the next run resumes from this file.
        self._sink_path = sink_path

    def _persist(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        self._by_digest[record["digest"]] = record
        if self._sink_path is not None:
            with self._sink_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # -- budget ---------------------------------------------------------
    def _price(self) -> tuple[float, float]:
        return PRICES_USD_PER_1K.get(self.model, (0.0, 0.0))

    def _guard(self, prompt: str, system: str | None) -> None:
        per_in, per_out = self._price()
        # Worst case for this call: the prompt plus the configured output
        # ceiling. Checked BEFORE sending, so the cap can never be crossed by
        # the call it is about to allow.
        worst = (estimate_tokens(prompt) + estimate_tokens(system or "")) / 1000 * per_in
        worst += 4096 / 1000 * per_out
        if self.spent_usd + worst > self.max_usd:
            raise SpendCapExceeded(
                f"spend cap ${self.max_usd:.2f} reached at ${self.spent_usd:.4f} "
                f"after {self.calls} calls"
            )

    def _account(self, prompt: str, system: str | None, answer: str) -> None:
        per_in, per_out = self._price()
        pin = estimate_tokens(prompt) + estimate_tokens(system or "")
        pout = estimate_tokens(answer)
        self.prompt_tokens += pin
        self.completion_tokens += pout
        self.spent_usd += pin / 1000 * per_in + pout / 1000 * per_out
        self.calls += 1

    # -- protocol -------------------------------------------------------
    async def _pace(self) -> None:
        """Keep the call rate under ``--min-interval`` seconds.

        The owner key is on the provider's free tier, whose per-minute request
        cap is enforced by the server (HTTP 429). Pacing is cheaper than
        retrying: a whole run of ~230 calls finishes in ~16 minutes instead of
        spending most of its wall clock in backoff.
        """
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)
        self._last_call_at = time.monotonic()

    @staticmethod
    def _server_hint(text: str) -> float | None:
        """The provider's own retry hint ('Please retry in 36.6s'), if present."""
        match = re.search(r"retry in ([\d.]+)\s*s", text, re.IGNORECASE)
        if match:
            return min(float(match.group(1)), 90.0)
        return None

    async def _call_with_retry(
        self,
        prompt: str,
        system: str | None,
        image: dict | None,
        sampling: Any,
    ) -> tuple[str, float]:
        """One provider call with pacing + backoff; returns (answer, elapsed)."""
        started = time.perf_counter()
        attempt = 0
        while True:
            await self._pace()
            try:
                answer = await self._inner.generate(
                    prompt, system=system, image=image, sampling=sampling
                )
                return answer, time.perf_counter() - started
            except ProviderError as exc:
                attempt += 1
                detail = str(exc)
                self.errors.append(
                    {
                        "kind": type(exc).__name__,
                        "detail": detail[:200],
                        "attempt": str(attempt),
                    }
                )
                if attempt >= self.MAX_ATTEMPTS:
                    if "quota" in detail.lower() or "429" in detail:
                        raise QuotaExhausted(
                            f"provider quota refused the call after {attempt} attempts: {detail[:300]}"
                        ) from exc
                    raise
                self.retries += 1
                hint = self._server_hint(detail)
                delay = hint if hint is not None else self.BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "live_provider_error attempt=%d wait_s=%.1f detail=%s",
                    attempt,
                    delay,
                    detail[:120],
                )
                await asyncio.sleep(delay)

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        image: dict | None = None,
        sampling: Any = None,
    ) -> str:
        key = prompt_digest(prompt, system, image)
        known = self._by_digest.get(key)
        if known is not None:
            self.resumed += 1
            return str(known["answer"])
        self._guard(prompt, system)
        answer, elapsed = await self._call_with_retry(prompt, system, image, sampling)
        self._account(prompt, system, answer)
        record = {
            "digest": key,
            "model": self.model,
            "prompt_chars": len(prompt),
            "answer": answer,
            "latency_ms": round(elapsed * 1000, 1),
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self._persist(record)
        return answer

    async def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        image: dict | None = None,
        sampling: Any = None,
    ) -> AsyncIterator[str]:
        key = prompt_digest(prompt, system, image)
        known = self._by_digest.get(key)
        if known is not None:
            # Resumed: replay the recorded text in fixed chunks so the caller
            # sees the same shape as a live stream.
            self.resumed += 1
            answer = str(known["answer"])
            for start in range(0, len(answer), 120):
                yield answer[start : start + 120]
            return
        self._guard(prompt, system)
        started = time.perf_counter()
        parts: list[str] = []
        async for delta in self._inner.stream(
            prompt, system=system, image=image, sampling=sampling
        ):
            parts.append(delta)
            yield delta
        answer = "".join(parts)
        self._account(prompt, system, answer)
        record = {
            "digest": key,
            "model": self.model,
            "prompt_chars": len(prompt),
            "answer": answer,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "streamed": True,
        }
        self._persist(record)

    async def aclose(self) -> None:
        close = getattr(self._inner, "aclose", None)
        if close is not None:
            await close()
