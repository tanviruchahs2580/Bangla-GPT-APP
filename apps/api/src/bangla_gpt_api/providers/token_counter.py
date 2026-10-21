"""A5-01: the exact vendor token counter, with the calibrated heuristic as
the documented fallback.

The context budget (services.context) must be measured in the target model's
own tokens. The vendor exposes that through a countTokens-style metadata
endpoint (Gemini REST ``countTokens``; no generation, no billing). The
default ``HeuristicTokenCounter`` (2.5 chars/token) is an UPPER bound: the
r3 calibration measured it counting 1.27x-1.58x the vendor count, and the
2026-10-19 vendor run (20 golden items, 120 countTokens calls, artifact
``eval/token_counter_calibration.json``) measured 1.07x-1.20x (mean 1.13x) —
still above 1, so every budget decision made on the heuristic stays
conservative. This adapter makes the exact path real and switchable:

* the production default stays the heuristic (settings.
  ``llm_exact_token_counting`` is False), because a serving turn must not
  block on a metadata HTTP round-trip per passage;
* when the flag is on (or an evaluation audit asks), :class:`ExactTokenCounter`
  asks the provider's ``count_tokens`` and falls back to the heuristic upper
  bound per call, so an endpoint outage degrades to the safe-side estimate
  and never breaks a turn;
* the counter records how it measured (``vendor_calls`` /
  ``fallback_calls``), so a trace and the calibration audit can tell honest
  vendor numbers from fallbacks.
"""

from __future__ import annotations

import logging

from bangla_gpt_api.services.context import HeuristicTokenCounter, TokenCounter

logger = logging.getLogger(__name__)


class ExactTokenCounter:
    """``TokenCounter`` over a provider's ``count_tokens`` (A5-01).

    ``count`` returns the vendor count when the provider answers, else the
    heuristic upper bound (the calibrated fallback), never an exception.
    """

    def __init__(self, provider: object, *, fallback: TokenCounter | None = None) -> None:
        self._provider = provider
        self._fallback = fallback or HeuristicTokenCounter()
        self.name = f"{getattr(provider, 'name', 'provider')}-countTokens"
        #: measurement provenance (calibration + honesty in traces)
        self.vendor_calls = 0
        self.fallback_calls = 0

    def count(self, text: str) -> int:
        count_tokens = getattr(self._provider, "count_tokens", None)
        if count_tokens is None or not callable(count_tokens):
            return self._fallback.count(text)
        try:
            vendor = count_tokens(text)
        except Exception:  # noqa: BLE001 - the fallback IS the contract
            logger.warning("count_tokens failed; using the heuristic upper bound")
            vendor = None
        if isinstance(vendor, int) and vendor >= 0:
            self.vendor_calls += 1
            return vendor
        self.fallback_calls += 1
        return self._fallback.count(text)

    @property
    def fell_back(self) -> bool:
        """True when any call had to use the heuristic upper bound."""
        return self.fallback_calls > 0


def provider_supports_count_tokens(provider: object) -> bool:
    """A provider usable with :class:`ExactTokenCounter` declares count_tokens.

    ``callable(getattr(...))`` instead of a Protocol attribute: providers that
    cannot count (e.g. no vendor endpoint yet) simply omit the method and the
    wiring falls back to the default heuristic counter.
    """
    return callable(getattr(provider, "count_tokens", None))
