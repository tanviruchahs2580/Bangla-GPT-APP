"""A8-05: the live-model evaluation run -- bounded, recorded, dated artifacts.

The hermetic gate (``evaluation.cli``) deliberately runs the mock provider so CI
needs no secrets. This script is the other half: it runs the SAME golden set
through the real provider, records every response so CI can replay them
deterministically, and writes dated artifacts a report can cite.

    cd apps/api
    python scripts/evaluate_live.py --split test --max-usd 3.00 \
        --model gemini-3.5-flash-lite --out-dir eval/live/2026-10-19

Design notes, each load-bearing:

* **Spend cap is enforced, not estimated.** Every provider call is checked
  against the accumulated estimate *before* it is sent; the cap aborts the run
  with a partial artifact rather than quietly billling past it. The estimate
  uses :data:`PRICES_USD_PER_1K` below -- the pricing read from the vendor page
  on :data:`PRICES_READ_ON` -- because ``services/costs.MODEL_COSTS_USD_PER_1K``
  is the product's *budgeting* table and may not carry the evaluation model.
* **The key is never printed, logged or written.** It comes from the process
  environment or ``apps/api/.env`` (gitignored), exactly like the server.
* **Recorded responses are the CI replay material.** ``recorded_responses.jsonl``
  is keyed by a digest of the exact prompt sent, so a replay can only answer a
  prompt that was actually asked, and a changed prompt misses (a loud, honest
  failure) instead of silently serving a stale answer.
* **Nothing here writes a tracked file**: all output goes under ``--out-dir``.

Exit codes: 0 = run completed, 1 = usage/configuration error, 2 = the run hit
the spend cap (artifacts are still written, marked ``partial``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
SRC = APP_ROOT / "src"
if str(SRC) not in sys.path:  # the script runs before the package is importable
    sys.path.insert(0, str(SRC))

from bangla_gpt_api.config import Settings  # noqa: E402
from bangla_gpt_api.data.loader import load_sample_corpus  # noqa: E402
from bangla_gpt_api.evaluation.live_recorder import (  # noqa: E402
    PRICES_READ_ON,
    PRICES_USD_PER_1K,
    BudgetedRecordingProvider,
    QuotaExhausted,
    SpendCapExceeded,
)
from bangla_gpt_api.providers import base as provider_base  # noqa: E402
from bangla_gpt_api.providers import get_provider  # noqa: E402
from bangla_gpt_api.providers.base import ProviderError  # noqa: E402
from bangla_gpt_api.services.tutor import TutorService  # noqa: E402


def _load_items(split: str) -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads(
        (APP_ROOT / "eval" / "golden_v2.json").read_text(encoding="utf-8")
    )
    items: list[dict[str, Any]] = data["items"]
    if split == "all":
        return items
    selected = [it for it in items if it.get("split", "dev") == split]
    if not selected:
        raise SystemExit(f"split {split!r} selected no items")
    return selected


def _redteam_items() -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads(
        (APP_ROOT / "eval" / "redteam_v2.json").read_text(encoding="utf-8")
    )
    items: list[dict[str, Any]] = data["items"]
    return items


def _dotenv_value(path: Path, name: str) -> str:
    """One value out of a dotenv file, without importing a parser for it."""
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _api_key() -> str:
    """The provider key from the environment or the gitignored apps/api/.env."""
    key = (
        os.environ.get("GEMINI_API_KEY", "") or _dotenv_value(APP_ROOT / ".env", "GEMINI_API_KEY")
    ).strip()
    if not key:
        raise SystemExit(
            "no GEMINI_API_KEY: set it in the process environment or in the "
            "gitignored apps/api/.env (the value is never printed here)"
        )
    return key


async def _run(args: argparse.Namespace) -> int:
    # The key is resolved explicitly and handed to Settings as a value: the
    # script must behave the same whether it is run from apps/api or from the
    # repo root, and the value must never appear in a Settings repr or a log.
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
    # Resume: an interrupted run continues from its own recordings instead of
    # paying for the same prompts again (responses are keyed by prompt digest).
    resume: list[dict[str, Any]] = []
    recordings_path = out_dir / "recorded_responses.jsonl"
    if args.resume and recordings_path.is_file():
        with recordings_path.open(encoding="utf-8") as fh:
            resume = [json.loads(line) for line in fh if line.strip()]
        print(f"RESUME: {len(resume)} recorded responses loaded from {recordings_path}")
    recorder = BudgetedRecordingProvider(
        provider,
        model=args.model,
        max_usd=args.max_usd,
        resume=resume,
        min_interval=args.min_interval,
        sink_path=recordings_path,
    )

    from bangla_gpt_api.evaluation.generation import (
        judge_prompt_path,
        judge_prompt_version,
        load_judge_harness,
        run_generation_report,
    )
    from bangla_gpt_api.retrieval.embedding import build_embedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    index = HybridIndex(load_sample_corpus(), build_embedder(settings))
    tutor = TutorService(index=index, provider=recorder, fast_provider=None)
    # The deliberate pacing delay (a free-tier rate limit, not product
    # behaviour) sits inside the provider call and therefore inside the tutor's
    # generation stage ceiling. Raise that ceiling for the run and say so in
    # the artifacts: latency from this run is NOT comparable to the
    # stage-latency harness's numbers.
    provider_base.STAGE_TIMEOUT_SECONDS["generation"] = args.generation_budget

    items = _load_items(args.split)
    redteam = _redteam_items() if not args.no_redteam else []
    print(
        f"LIVE RUN split={args.split} items={len(items)} redteam={len(redteam)} "
        f"model={args.model} cap=${args.max_usd:.2f} key_len={len(settings.gemini_api_key or '')}"
    )

    started = datetime.now(UTC)
    partial = False
    abort_reason = ""
    try:
        report = await run_generation_report(tutor, items, unsafe_items=redteam)
    except SpendCapExceeded as exc:
        print(f"SPEND CAP: {exc}")
        report = {"aborted": str(exc)}
        abort_reason = f"spend cap: {exc}"
        partial = True
    except QuotaExhausted as exc:
        print(f"QUOTA: {exc}")
        report = {"aborted": str(exc)}
        abort_reason = f"provider quota: {exc}"
        partial = True
    except ProviderError as exc:
        # A provider fault (a stage timeout, a hard 4xx) stops the run; the
        # recordings already on disk make the next attempt cheap.
        print(f"PROVIDER ERROR: {exc}")
        report = {"aborted": str(exc)}
        abort_reason = f"provider error: {exc}"
        partial = True

    finished = datetime.now(UTC)

    report["run_conditions"] = {
        "provider": f"live ({args.model}, key from env/.env, never logged)",
        "pacing": (
            f"{args.min_interval}s between calls (free-tier request cap); the "
            f"generation stage ceiling was raised to {args.generation_budget}s for this "
            "run, so latency here is not a product measurement"
        ),
        "judge": "disabled: metrics of record use the deterministic local_overlap "
        "fallback; the LLM-judge harness stays dormant until 50+ human labels exist",
        "index": f"hermetic sample corpus ({len(index.chunks)} chunks)",
        "items": len(items),
        "split": args.split,
        "redteam_items": len(redteam),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "partial": partial,
        "abort_reason": abort_reason,
        "resumed_responses": recorder.resumed,
        "retried_calls": recorder.retries,
        "provider_calls": recorder.calls,
        "provider_errors": recorder.errors[:20],
        "prompt_tokens_est": recorder.prompt_tokens,
        "completion_tokens_est": recorder.completion_tokens,
        "estimated_cost_usd": round(recorder.spent_usd, 6),
        "prices_usd_per_1k": PRICES_USD_PER_1K.get(args.model),
        "prices_source": "https://ai.google.dev/gemini-api/docs/pricing",
        "prices_read_on": PRICES_READ_ON,
    }
    report["judge_prompt_version"] = judge_prompt_version(judge_prompt_path(APP_ROOT))
    report["judge_agreement"] = load_judge_harness(APP_ROOT)

    (out_dir / "live_generation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (out_dir / "recorded_responses.jsonl").open("w", encoding="utf-8") as fh:
        for rec in recorder.records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    metrics = {k: v for k, v in sorted(report.items()) if isinstance(v, (int, float))}
    lines = [
        f"# Live evaluation -- {args.model}",
        "",
        f"- split: `{args.split}` ({len(items)} items), red-team: {len(redteam)}",
        f"- provider calls: {recorder.calls} (retried: {recorder.retries}); "
        f"served from recording: {recorder.resumed}; errors: {len(recorder.errors)}",
        f"- estimated spend: ${recorder.spent_usd:.4f} of the ${args.max_usd:.2f} cap",
        f"- started {started.isoformat(timespec='seconds')} / finished "
        f"{finished.isoformat(timespec='seconds')}",
        f"- partial: {partial}",
        "",
        "## Metrics",
        "",
        "| metric | value |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in metrics.items()]
    lines += [
        "",
        "Judge-human agreement is deliberately not reported: the sample carries no",
        "human labels (owner action), and an unmeasured agreement number would be a",
        "fabricated metric.",
        "",
        "Replay material: `recorded_responses.jsonl`, keyed by the digest of the",
        "exact prompt sent (prompt + system + image prefix).",
    ]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        f"LIVE RUN {'PARTIAL' if partial else 'DONE'} calls={recorder.calls} "
        f"spend=${recorder.spent_usd:.4f} errors={len(recorder.errors)}"
    )
    for key in (
        "citation_precision",
        "citation_recall",
        "abstention_recall",
        "false_refusal_rate",
        "format_validity",
        "response_language_correctness",
        "refusal_correctness_unsafe",
        "grounded_items",
    ):
        if key in report:
            print(f"  {key} = {report[key]}")
    print(f"artifacts: {out_dir}")
    return 2 if partial else 0


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


async def _run_ttft_profile(args: argparse.Namespace) -> int:
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
    recorder = BudgetedRecordingProvider(
        provider,
        model=args.model,
        max_usd=args.max_usd,
        resume=[],
        min_interval=args.min_interval,
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

    failures: list[str] = []

    async def one(item: dict[str, Any]) -> None:
        """One streamed answer; a failed call is recorded, never aborts the run.

        A latency profile that dies on the first 429 describes nothing: the
        failures are counted and reported next to the percentiles.
        """
        async with gate:
            await pacer.wait()
            started = time.perf_counter()
            ttft: float | None = None
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
            "budgets": {
                "ttft_p95_seconds": 3.0,
                "total_p95_seconds": 12.0,
                "retrieval_p95_ms": 300.0,
            },
            "caveat": (
                "TTFT and total include the free-tier pacing sleep, which sits "
                "inside the provider call; the pacing is removed from the "
                "product path, so these are upper bounds. Retrieval-only is "
                "measured without a provider call."
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


def main(argv: Iterator[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A8-05 live-model evaluation run")
    parser.add_argument("--split", choices=["all", "dev", "test"], default="test")
    parser.add_argument("--model", default="gemini-3.5-flash-lite")
    parser.add_argument("--max-usd", type=float, default=3.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument(
        "--generation-budget",
        type=float,
        default=180.0,
        help="generation stage ceiling for this run, in seconds (pacing + retries "
        "must fit inside it)",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=4.2,
        help="seconds between provider calls (free-tier keys cap requests per minute; "
        "4.2 keeps a run under 15/min)",
    )
    parser.add_argument("--no-redteam", action="store_true")
    parser.add_argument(
        "--ttft-profile",
        action="store_true",
        help="A9-01: measure stage latency (TTFT, full answer, retrieval-only) "
        "at a stated concurrency instead of running the generation report",
    )
    parser.add_argument("--concurrency", type=int, default=2, help="streams in flight (A9-01)")
    parser.add_argument("--profile-items", type=int, default=20, help="answers to measure")
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="serve already-recorded prompts from --out-dir instead of re-calling (default on)",
    )
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument(
        "--out-dir",
        default=f"eval/live/{datetime.now(UTC).date().isoformat()}",
        help="artifact directory (relative to apps/api)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.ttft_profile:
            return asyncio.run(_run_ttft_profile(args))
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
