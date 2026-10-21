"""A9-01: stage-level latency (p50/p95/p99) under a stated concurrency.

The audit's A9-01 status was PARTIAL: only the retrieval stage had a measured
percentile (and a histogram), and nothing reported time-to-first-token or the
full-answer latency at a stated concurrency. This harness instruments the real
``TutorService`` pipeline *from outside* (instance-method wrappers; no service
code changes) and records, per request:

``retrieval`` (the CPU search, the sub-stage ``rerank`` measured inside it),
``context_build``, ``provider_select``, ``llm_ttft`` and ``llm_total`` (on the
streaming path; the non-streaming path has no first token), ``post_process``,
``query_processing`` (the un-instrumented remainder: normalization, safety
screen, follow-up condensation, response handling) and ``wall``.

Concurrency is stated, not implied: the harness runs ``--concurrency`` levels
with independent asyncio tasks, so the percentiles in the report are the
percentiles at that concurrency on this host with the mock provider. The
limits are recorded in the artifact: one in-process worker, mock provider
(so ``llm_ttft`` is pipeline TTFT, not model TTFT -- a live-provider run is
the owner action that replaces it), shared-host timing.

Budgets are the A9-01 proposals, marked per row: TTFT p95 <= 3 s, full answer
p95 <= 12 s, retrieval-only p95 <= 300 ms.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any

#: A9-01 budget proposals, quoted here so the report marks each row against a
#: stated number instead of a feeling.
BUDGETS = {
    "llm_ttft_p95_ms": 3000,
    "full_answer_p95_ms": 12000,
    "retrieval_p95_ms": 300,
}

_STAGE_FIELDS = (
    "query_processing_ms",
    "retrieval_ms",
    "rerank_ms",
    "context_build_ms",
    "provider_select_ms",
    "llm_ttft_ms",
    "llm_total_ms",
    "post_process_ms",
)


@dataclass
class StageTimings:
    """One request's stage durations in milliseconds (``None`` = stage absent)."""

    query_processing_ms: float = 0.0
    retrieval_ms: float = 0.0
    rerank_ms: float = 0.0
    context_build_ms: float = 0.0
    provider_select_ms: float = 0.0
    llm_ttft_ms: float | None = None
    llm_total_ms: float = 0.0
    post_process_ms: float = 0.0
    wall_ms: float = 0.0
    grounded: bool = False
    #: Stage fields this request actually exercised. A stage the path never
    #: calls (the streaming path has no ``_assemble``) must be absent from the
    #: aggregate, not reported as 0.0 -- a zero nobody measured is a lie.
    measured: set[str] = field(default_factory=set)

    def finalize(self) -> None:
        """Fill ``query_processing_ms`` as the measured remainder.

        The instrumented stages are wrapped instance methods; anything the
        pipeline does outside them (normalization, safety screen, follow-up
        condensation, event plumbing) shows up here. The field is named for
        that remainder and documented as such -- a new stage added to the
        service is absorbed here, which can only under-report a *new* stage,
        never invent time for an existing one.
        """
        instrumented = (
            self.retrieval_ms
            + self.context_build_ms
            + self.provider_select_ms
            + self.llm_total_ms
            + self.post_process_ms
        )
        self.query_processing_ms = round(max(self.wall_ms - instrumented, 0.0), 3)
        self.measured |= {"query_processing_ms", "wall_ms"}


_timings_var: contextvars.ContextVar[StageTimings | None] = contextvars.ContextVar(
    "stage_timings", default=None
)


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


@dataclass
class _Instrumentation:
    """Instance-method wrappers around the real tutor; restored on exit."""

    tutor: Any
    _originals: dict[str, Any] = field(default_factory=dict)

    def __enter__(self) -> _Instrumentation:
        def wrap(name: str, field_name: str) -> None:
            original = getattr(self.tutor, name)

            @functools.wraps(original)
            async def timed_async(*args: Any, **kwargs: Any) -> Any:
                timings = _timings_var.get()
                started = _now_ms()
                try:
                    return await original(*args, **kwargs)
                finally:
                    elapsed = _now_ms() - started
                    if timings is not None:
                        setattr(timings, field_name, getattr(timings, field_name) + elapsed)
                        timings.measured.add(field_name)

            @functools.wraps(original)
            def timed_sync(*args: Any, **kwargs: Any) -> Any:
                timings = _timings_var.get()
                started = _now_ms()
                try:
                    return original(*args, **kwargs)
                finally:
                    elapsed = _now_ms() - started
                    if timings is not None:
                        setattr(timings, field_name, getattr(timings, field_name) + elapsed)
                        timings.measured.add(field_name)

            is_async = asyncio.iscoroutinefunction(original)
            self._originals[name] = original
            setattr(self.tutor, name, timed_async if is_async else timed_sync)

        # Rerank is a stage *inside* retrieval: measured separately (as a
        # sub-stage of retrieval_ms, not an extra cost). It runs inside the
        # retrieval thread -- the timings object travels by contextvar, which
        # asyncio.to_thread copies into the worker.
        wrap("_retrieve_and_gate", "retrieval_ms")
        wrap("_prompt_blocks", "context_build_ms")
        wrap("_select_provider", "provider_select_ms")
        # Only _generate is wrapped: a grounded-regeneration retry calls it
        # again and accumulates into llm_total_ms, so the retry's model time is
        # counted exactly once (wrapping the caller too would double-count it).
        wrap("_generate", "llm_total_ms")
        wrap("_assemble", "post_process_ms")
        self._wrap_reranker()
        return self

    def _wrap_reranker(self) -> None:
        index = getattr(self.tutor, "index", None)
        if index is None:  # nothing to wrap; also narrows the setattr below
            return
        reranker = getattr(index, "reranker", None)
        if reranker is None:
            return
        self._originals["_reranker"] = reranker

        @functools.wraps(reranker)
        def timed_rerank(query: str, candidates: list) -> Any:
            timings = _timings_var.get()
            started = _now_ms()
            try:
                return reranker(query, candidates)
            finally:
                if timings is not None:
                    timings.rerank_ms += _now_ms() - started
                    timings.measured.add("rerank_ms")

        index.reranker = timed_rerank

    def __exit__(self, *exc_info: Any) -> None:
        for name, original in self._originals.items():
            if name == "_reranker":
                self.tutor.index.reranker = original
            else:
                setattr(self.tutor, name, original)
        self._originals.clear()


async def _one_ask(
    tutor: Any, question: str, class_level: int, subject: str | None
) -> StageTimings:
    timings = StageTimings()
    token = _timings_var.set(timings)
    started = _now_ms()
    try:
        response = await tutor.ask(question, class_level, subject)
        timings.grounded = bool(getattr(response, "grounded", False))
    finally:
        _timings_var.reset(token)
        timings.wall_ms = round(_now_ms() - started, 3)
        timings.finalize()
    return timings


async def _one_stream(
    tutor: Any, question: str, class_level: int, subject: str | None
) -> StageTimings:
    """One streaming turn: TTFT is the first ``token`` event, total is ``final``."""
    timings = StageTimings()
    token = _timings_var.set(timings)
    started = _now_ms()
    generation_started: float | None = None
    try:
        async for event in tutor.ask_stream(question, class_level, subject):
            if event.type == "token":
                if generation_started is None:
                    generation_started = _now_ms()
                if timings.llm_ttft_ms is None:
                    timings.llm_ttft_ms = round(_now_ms() - started, 3)
                    timings.measured.add("llm_ttft_ms")
            elif event.type == "final":
                response = getattr(event, "response", None)
                timings.grounded = bool(getattr(response, "grounded", False))
    finally:
        _timings_var.reset(token)
        timings.wall_ms = round(_now_ms() - started, 3)
        # The streaming path's "LLM total" is time to the last token (the
        # final event), measured on the wrapper's clock.
        if generation_started is not None:
            timings.llm_total_ms = round(max(timings.llm_total_ms, timings.wall_ms), 3)
            timings.measured.add("llm_total_ms")
        timings.finalize()
    return timings


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile, 3-decimal ms; 0.0 for an empty sample."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(min(int(len(ordered) * fraction), len(ordered) - 1), 0)
    return round(ordered[index], 3)


def _block(samples: list[StageTimings], field_name: str) -> dict[str, float]:
    values = [
        float(getattr(sample, field_name))
        for sample in samples
        if field_name in sample.measured and getattr(sample, field_name) is not None
    ]
    if not values:
        return {"n": 0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "mean_ms": 0.0}
    return {
        "n": len(values),
        "p50_ms": percentile(values, 0.5),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "mean_ms": round(statistics.fmean(values), 3),
    }


async def run_level(
    tutor: Any,
    questions: list[tuple[str, int, str | None]],
    *,
    concurrency: int,
    iterations: int,
    mode: str = "ask",
) -> dict[str, Any]:
    """One concurrency level over the question list, repeated ``iterations`` times."""
    semaphore = asyncio.Semaphore(concurrency)

    async def one(index: int) -> StageTimings:
        question, class_level, subject = questions[index % len(questions)]
        async with semaphore:
            if mode == "stream":
                return await _one_stream(tutor, question, class_level, subject)
            return await _one_ask(tutor, question, class_level, subject)

    started = time.perf_counter()
    samples = await asyncio.gather(*(one(index) for index in range(iterations)))
    wall = time.perf_counter() - started
    return {
        "concurrency": concurrency,
        "iterations": iterations,
        "mode": mode,
        "wall_seconds": round(wall, 3),
        "throughput_rps": round(iterations / wall, 2) if wall else 0.0,
        "grounded_rate": round(sum(1 for sample in samples if sample.grounded) / len(samples), 4)
        if samples
        else 0.0,
        "stages": {name: _block(list(samples), name) for name in _STAGE_FIELDS},
        "full_answer": {name: _block(list(samples), name) for name in ("wall_ms",)},
    }


def budgets_row(level: dict[str, Any]) -> dict[str, Any]:
    """The A9-01 budget rows for one concurrency level, marked pass/fail."""
    retrieval_p95 = level["stages"]["retrieval_ms"]["p95_ms"]
    ttft_p95 = level["stages"]["llm_ttft_ms"]["p95_ms"]
    answer_p95 = level["full_answer"]["wall_ms"]["p95_ms"]
    ttft_measured = level["stages"]["llm_ttft_ms"]["n"] > 0
    return {
        "concurrency": level["concurrency"],
        "retrieval_p95_ms": retrieval_p95,
        "retrieval_budget_ms": BUDGETS["retrieval_p95_ms"],
        "retrieval_within_budget": retrieval_p95 <= BUDGETS["retrieval_p95_ms"],
        "ttft_p95_ms": ttft_p95 if ttft_measured else None,
        "ttft_budget_ms": BUDGETS["llm_ttft_p95_ms"],
        "ttft_within_budget": (ttft_p95 <= BUDGETS["llm_ttft_p95_ms"] if ttft_measured else None),
        "full_answer_p95_ms": answer_p95,
        "full_answer_budget_ms": BUDGETS["full_answer_p95_ms"],
        "full_answer_within_budget": answer_p95 <= BUDGETS["full_answer_p95_ms"],
    }


#: Deterministic question mix: six real sample-corpus questions spread over
#: classes and subjects, cycled so no single cache entry answers everything.
QUESTIONS: tuple[tuple[str, int, str | None], ...] = (
    ("কোষ কী?", 6, "science"),
    ("সালোকসংশ্লেষণ কী?", 6, "science"),
    ("ভগ্নাংশ কী?", 6, "mathematics"),
    ("নিউটনের প্রথম সূত্র কী?", 6, "science"),
    ("গতির প্রকারভেদ কী?", 6, "science"),
    ("পানিচক্র কী?", 6, "science"),
)


async def build_report(
    *,
    concurrency_levels: tuple[int, ...] = (1, 8),
    iterations: int = 30,
    mode: str = "ask",
    include_stream: bool = True,
) -> dict[str, Any]:
    """Run the level ladder in-process and return the stage-latency report."""
    import platform
    import sys

    from bangla_gpt_api.evaluation.harness import build_hermetic_tutor, hermetic_settings
    from bangla_gpt_api.services.trace_meta import index_fingerprint

    tutor = build_hermetic_tutor(hermetic_settings())
    levels: list[dict[str, Any]] = []
    with _Instrumentation(tutor):
        for concurrency in concurrency_levels:
            levels.append(
                await run_level(
                    tutor,
                    list(QUESTIONS),
                    concurrency=concurrency,
                    iterations=iterations,
                    mode=mode,
                )
            )
        if include_stream:
            # One stream level: TTFT only exists on the streaming path.
            levels.append(
                await run_level(
                    tutor,
                    list(QUESTIONS),
                    concurrency=concurrency_levels[0],
                    iterations=iterations,
                    mode="stream",
                )
            )
    return {
        "generated_by": "bangla_gpt_api.evaluation.stage_latency",
        "run_conditions": {
            "host": platform.node(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "corpus": "bundled-sample",
            "corpus_fingerprint": index_fingerprint(tutor.index),
            "provider": "mock -- llm_ttft is pipeline TTFT, NOT model TTFT",
            "workers": 1,
            "mode_mix": f"ask at {list(concurrency_levels)} + stream at "
            f"{concurrency_levels[0] if include_stream else 'n/a'}",
            "iterations_per_level": iterations,
            "questions": len(QUESTIONS),
        },
        "budgets": BUDGETS,
        "levels": levels,
        "budget_checks": [budgets_row(level) for level in levels],
        "notes": (
            "Stages are wrapped instance methods of the real TutorService; "
            "query_processing_ms is the measured remainder (wall minus the "
            "instrumented stages). rerank_ms is a sub-stage of retrieval_ms, "
            "not an extra cost. Latency is host-dependent; compare within one run."
        ),
    }


def markdown_summary(report: dict) -> str:
    """The stage table for docs; generated, never hand-copied."""
    lines = [
        "| Level | Stage | n | p50 ms | p95 ms | p99 ms |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for level in report["levels"]:
        label = f"c{level['concurrency']} {level['mode']}"
        for stage, block in level["stages"].items():
            if block["n"] == 0:
                continue
            lines.append(
                f"| {label} | {stage} | {block['n']} | {block['p50_ms']} | "
                f"{block['p95_ms']} | {block['p99_ms']} |"
            )
        full = level["full_answer"]["wall_ms"]
        lines.append(
            f"| {label} | full_answer | {full['n']} | {full['p50_ms']} | "
            f"{full['p95_ms']} | {full['p99_ms']} |"
        )
    return "\n".join(lines)


def sample_dict(sample: StageTimings) -> dict[str, Any]:
    """A plain-dict view of one sample (tests and JSON writers)."""
    return asdict(sample)


__all__ = [
    "BUDGETS",
    "QUESTIONS",
    "StageTimings",
    "budgets_row",
    "build_report",
    "markdown_summary",
    "percentile",
    "run_level",
    "sample_dict",
]
