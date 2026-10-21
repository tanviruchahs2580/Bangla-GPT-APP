"""A5-01: measure the evidence context budget with the exact vendor counter.

The 2.5-chars/token heuristic is an UPPER bound (calibration measured it
counting 1.27x-1.58x the vendor count on Bangla text). This audit re-draws
that calibration on demand: for a sample of golden questions it retrieves
evidence and measures the SAME prompt under the heuristic counter and the
provider's own ``count_tokens`` endpoint (Gemini REST countTokens -- a
free-tier metadata request, never a generation call), then reports the ratio
and the budget impact (tokens used / passages kept under each counter).

Honesty rules:
* the provider is named in the artifact; a provider whose count is not a
  vendor endpoint (the mock reports the heuristic) sets
  ``count_tokens_is_vendor = False``, and the artifact says so;
* per-call vendor failures fall back to the heuristic and are counted
  (``fallback_calls``), never hidden;
* nothing here calls ``generate`` -- the audit is metadata-only.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bangla_gpt_api.config import Settings
from bangla_gpt_api.services.context import (
    DEFAULT_CHARS_PER_TOKEN,
    HeuristicTokenCounter,
    select_passages,
)

_READING_NOTE = (
    "ratio > 1 means the heuristic upper bound over-counts relative to the "
    "vendor; the 2400-token budget planned on the heuristic therefore fits MORE "
    "vendor tokens than assumed -- the conservative direction"
)
_VENDORED_NOTE = "every measurement came from the provider's count_tokens endpoint"
_FALLBACK_NOTE = (
    "the counter fell back to the calibrated heuristic upper bound on one or "
    "more calls (fallback_calls > 0); ratios below are not pure vendor counts"
)
_MOCK_NOTE = (
    "the mock provider's count IS the calibrated heuristic (count_tokens_is_vendor "
    "is False), so these ratios are heuristic-over-heuristic: run against the real "
    "provider (LLM_PROVIDER=gemini + GEMINI_API_KEY) for vendor numbers"
)


def _load_corpus(settings: Settings) -> list[Any]:
    """The corpus the audit measures: the NCTB build when present, else sample."""
    if settings.nctb_corpus_dir:
        from pathlib import Path as _Path

        from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

        root = _Path(settings.nctb_corpus_dir)
        chunks = load_nctb_corpus(
            root / "normalized", quality_report_path=root / "quality_report.json"
        )
        if chunks:
            return chunks
    from bangla_gpt_api.data.loader import load_sample_corpus

    return load_sample_corpus()


class _NoVendorProvider:
    """Stand-in that records WHY no vendor measurement is possible."""

    name = "none"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def count_tokens(self, _text: str) -> int:  # pragma: no cover - never used
        raise RuntimeError(self.reason)


def _load_provider(settings: Settings) -> Any:
    """The provider whose count_tokens measures the budget (or an honest none).

    Reads only the provider settings; the audit never generates.
    """
    if settings.llm_provider == "gemini" and settings.gemini_api_key:
        from bangla_gpt_api.providers.gemini import build_gemini_provider

        try:
            return build_gemini_provider(settings)
        except Exception as exc:  # noqa: BLE001 - recorded, never raised into eval
            return _NoVendorProvider(reason=f"gemini provider unavailable: {type(exc).__name__}")
    if settings.llm_provider == "mock":
        from bangla_gpt_api.providers.mock import MockLLMProvider

        return MockLLMProvider()
    return _NoVendorProvider(reason="no provider with count_tokens configured")


def build_audit(
    *,
    settings: Settings,
    golden_path: Path,
    sample: int = 25,
    seed: int = 20260825,
    provider: Any = None,
) -> dict[str, Any]:
    """Measure the same evidence blocks under both counters."""
    provider = provider or _load_provider(settings)
    counter = _counter_for(provider)
    picked = _pick_items(golden_path, sample=sample, seed=seed)
    index, heuristic = _build_index(settings), HeuristicTokenCounter()

    rows = [r for r in (_measure_row(item, index, heuristic, counter) for item in picked) if r]

    ratios = [
        r["ratio_heuristic_over_measured"] for r in rows if r["ratio_heuristic_over_measured"]
    ]
    return {
        "schema": "token_counter_calibration/v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": getattr(provider, "name", "unknown"),
        "counter": counter.name,
        "vendor_endpoint": _is_vendor(provider) and not getattr(counter, "fell_back", False),
        "note": _counter_note(provider, counter, **_vendor_state(provider, counter)),
        "fallback_calls": int(getattr(counter, "fallback_calls", 0)),
        "vendor_calls": int(getattr(counter, "vendor_calls", 0)),
        "sample_size": len(rows),
        "seed": seed,
        "heuristic_chars_per_token": DEFAULT_CHARS_PER_TOKEN,
        "ratio_summary": _ratio_summary(ratios),
        "reading": _READING_NOTE,
        "samples": rows,
    }


def _is_vendor(provider: Any) -> bool:
    return bool(
        callable(getattr(provider, "count_tokens", None))
        and getattr(provider, "count_tokens_is_vendor", True)
    )


def _vendor_state(provider: Any, counter: Any) -> dict[str, bool]:
    has_count_tokens = callable(getattr(provider, "count_tokens", None))
    return {
        "has_count_tokens": has_count_tokens,
        "is_vendor": _is_vendor(provider) and has_count_tokens,
    }


def _ratio_summary(ratios: list[float]) -> dict[str, float | None]:
    return {
        "mean": round(sum(ratios) / len(ratios), 4) if ratios else None,
        "min": round(min(ratios), 4) if ratios else None,
        "max": round(max(ratios), 4) if ratios else None,
    }


def _counter_for(provider: Any) -> Any:
    """The exact vendor counter when the provider offers countTokens, else the
    calibrated heuristic (the artifact names which one ran -- never both)."""
    counter: Any = HeuristicTokenCounter()
    if callable(getattr(provider, "count_tokens", None)):
        from bangla_gpt_api.providers.token_counter import ExactTokenCounter

        counter = ExactTokenCounter(provider)
    return counter


def _pick_items(golden_path: Path, *, sample: int, seed: int) -> list[dict[str, Any]]:
    """Deterministic stratified-capable sample of the golden set."""
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    items = data["items"]
    rng = random.Random(seed)  # noqa: S311 - sampling, not crypto
    return rng.sample(items, min(sample, len(items)))


def _build_index(settings: Settings) -> Any:
    from bangla_gpt_api.retrieval.embedding import build_embedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    return HybridIndex(_load_corpus(settings), build_embedder(settings))


def _counter_note(provider: Any, counter: Any, *, has_count_tokens: bool, is_vendor: bool) -> str:
    """Which honesty note the artifact carries, from the observed run state."""
    if not has_count_tokens:
        return getattr(provider, "reason", "no provider with count_tokens configured")
    if not is_vendor:
        return _MOCK_NOTE
    if getattr(counter, "fell_back", False):
        return _FALLBACK_NOTE
    return _VENDORED_NOTE


def _measure_row(
    item: dict[str, Any],
    index: Any,
    heuristic: Any,
    counter: Any,
) -> dict[str, Any] | None:
    """One calibration row: the same evidence window under both counters."""
    question = str(item.get("question", "")).strip()
    meta = item.get("meta", {}) or {}
    if not question:
        return None
    hits = index.search(
        question,
        class_level=int(meta.get("class_level", 6)),
        subject=meta.get("subject"),
        top_k=3,
    )
    if not hits:
        return None
    heur_selection = select_passages(hits, counter=heuristic)
    exact_selection = select_passages(hits, counter=counter)
    heur_tokens = heur_selection.tokens
    measured_tokens = exact_selection.tokens
    row: dict[str, Any] = {
        "item_id": item.get("id"),
        "evidence_chars": sum(len(p.text) for p in heur_selection.passages),
        "heuristic_tokens": heur_tokens,
        "measured_tokens": measured_tokens,
        "measured_by": counter.name,
        "passages_kept_heuristic": len(heur_selection.passages),
        "passages_kept_measured": len(exact_selection.passages),
        "ratio_heuristic_over_measured": (
            round(heur_tokens / measured_tokens, 4) if measured_tokens else None
        ),
    }
    return row


def write_audit(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


__all__ = ["build_audit", "write_audit"]
