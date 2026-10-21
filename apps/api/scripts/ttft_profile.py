"""A9-01: the live stage-latency profile (TTFT, full answer, retrieval-only).

Split out of ``scripts/evaluate_live.py`` so neither script grows past the
file-size ratchet; ``evaluate_live.py --ttft-profile`` calls
:func:`run_ttft_profile`. The recording it writes has the same shape as the
generation run's and is replayable by the same provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]


from _live_common import _api_key, _load_items  # noqa: E402

from bangla_gpt_api.config import Settings  # noqa: E402
from bangla_gpt_api.data.loader import load_sample_corpus  # noqa: E402
from bangla_gpt_api.evaluation.live_recorder import (  # noqa: E402
    BudgetedRecordingProvider,
)
from bangla_gpt_api.providers import base as provider_base  # noqa: E402
from bangla_gpt_api.providers import get_provider  # noqa: E402
from bangla_gpt_api.services.tutor import TutorService  # noqa: E402


class _StartPacer:
    """Space the START of provider calls by ``min_interval`` seconds (A9-01).

    Concurrency overlaps the streams; the free tier's cap is on requests per
    minute, so the interval is enforced between call starts rather than
    between call ends (a paced run at concurrency 2 stays under 15/min).
    """

    def __init__(self, min_interval: float) -> None:
        self._interval = float(min_interval)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._interval - (now - self._last)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


def _percentiles(values: list[float]) -> dict[str, float]:
    """p50/p95/p99 of a sample, with the sample size stated next to them.

    ``p99`` at n=20 is the largest observation, not a tail estimate; the
    artifact records ``n`` so a reader can tell the two apart.
    """
    ordered = sorted(values)
    if not ordered:
        return {}

    def at(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return round(ordered[index], 3)

    return {
        "n": len(ordered),
        "p50": at(0.50),
        "p95": at(0.95),
        "p99": at(0.99),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
    }


async def run_ttft_profile(args: argparse.Namespace) -> int:
    """A9-01: stage latency at a stated concurrency, against the live model.

    Measures, for N streaming answers at ``--concurrency`` (default 2) under
    the free-tier pacing: time-to-first-token and full-answer wall time per
    call (p50/p95/p99), plus the retrieval-only stage measured on the same
    questions without a provider call (the quieter path the budget applies
    to). Writes ``ttft_profile.json`` next to the run's other artifacts and
    records every streamed answer for replay.
    """
    settings = Settings(
        env="test",
        llm_provider="gemini",
        gemini_model=args.model,
        gemini_api_key=_api_key(),
        llm_max_retries=args.retries,
    )
    provider = get_provider(settings)
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = APP_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    from bangla_gpt_api.retrieval.embedding import build_embedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    index = HybridIndex(load_sample_corpus(), build_embedder(settings))
    # A9-01 measurement correctness: the free-tier pacing is HARNESS overhead,
    # not product latency, so it belongs outside the timed window. The pacer
    # below spaces call starts; the recorder must not also sleep, or the sleep
    # lands inside the measurement and reports a product number the product
    # does not have.
    recorder = BudgetedRecordingProvider(
        provider,
        model=args.model,
        max_usd=args.max_usd,
        resume=[],
        min_interval=0.0,
        sink_path=out_dir / "ttft_recorded_responses.jsonl",
    )
    tutor = TutorService(index=index, provider=recorder, fast_provider=None)
    provider_base.STAGE_TIMEOUT_SECONDS["generation"] = args.generation_budget

    items = _load_items(args.split)[: args.profile_items]
    print(
        f"TTFT PROFILE items={len(items)} concurrency={args.concurrency} "
        f"model={args.model} pacing={args.min_interval}s cap=${args.max_usd:.2f}"
    )

    # --- retrieval-only stage: no provider call, so it is measured alone.
    retrieval_ms: list[float] = []
    for item in items:
        started = time.perf_counter()
        tutor.retrieved_sources(item["question"], item["class_level"], item.get("subject") or None)
        retrieval_ms.append((time.perf_counter() - started) * 1000.0)

    gate = asyncio.Semaphore(args.concurrency)
    pacer = _StartPacer(args.min_interval)
    ttft_s: list[float] = []
    total_s: list[float] = []
    prompt_chars: list[int] = []

    failures: list[str] = []

    async def one(item: dict[str, Any]) -> None:
        """One streamed answer; a failed call is recorded, never aborts the run.

        A latency profile that dies on the first 429 describes nothing: the
        failures are counted and reported next to the percentiles. The clock
        starts AFTER the pacer's wait, so the per-call numbers are the
        pipeline's own latency and not the harness's throttle.
        """
        async with gate:
            await pacer.wait()
            started = time.perf_counter()
            ttft: float | None = None
            prompt_chars.append(len(str(item.get("question") or "")))
            try:
                async for event in tutor.ask_stream(
                    item["question"], item["class_level"], item.get("subject") or None
                ):
                    if event.type == "token" and ttft is None:
                        ttft = time.perf_counter() - started
                    elif event.type == "final":
                        total_s.append(time.perf_counter() - started)
            except Exception as exc:  # noqa: BLE001 -- a profile reports failures
                failures.append(f"{type(exc).__name__}: {exc}"[:160])
                return
            if ttft is not None:
                ttft_s.append(ttft)

    started = datetime.now(UTC)
    await asyncio.gather(*(one(item) for item in items))
    elapsed = (datetime.now(UTC) - started).total_seconds()

    report = {
        "generated_by": "scripts/evaluate_live.py --ttft-profile",
        "A9-01": {
            "concurrency": args.concurrency,
            "items": len(items),
            "model": args.model,
            "pacing_seconds_between_call_starts": args.min_interval,
            "wall_seconds": round(elapsed, 1),
            "calls": {"attempted": len(items), "succeeded": len(total_s), "failed": len(failures)},
            "failure_samples": failures[:5],
            "ttft_seconds": _percentiles(ttft_s),
            "total_answer_seconds": _percentiles(total_s),
            "retrieval_only_ms": _percentiles(retrieval_ms),
            "question_chars": _percentiles([float(value) for value in prompt_chars]),
            "budgets": {
                "ttft_p95_seconds": 3.0,
                "total_p95_seconds": 12.0,
                "retrieval_p95_ms": 300.0,
            },
            "caveat": (
                "Per-call timings start AFTER the harness pacer's wait: the "
                "free-tier pacing is harness overhead, not product latency, and "
                "it is excluded by construction (the recorder is built with "
                "min_interval=0 so nothing sleeps inside the measured window). "
                "What remains is the pipeline plus the free-tier model's own "
                "queueing on this host. Retrieval-only is measured without a "
                "provider call."
            ),
            "recordings": str(out_dir / "ttft_recorded_responses.jsonl"),
        },
        "run_conditions": {
            "host": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "started": started.isoformat(timespec="seconds"),
        },
    }
    path = out_dir / "ttft_profile.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    section = report["A9-01"]
    for label in ("ttft_seconds", "total_answer_seconds", "retrieval_only_ms"):
        print(f"  {label}: {section[label]}")
    print(f"written -> {path}")
    return 0
