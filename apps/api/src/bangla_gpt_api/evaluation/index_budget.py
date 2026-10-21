"""A3-05: index build time, size, memory and cold-start, against a budget.

The audit's A3-05 status was PARTIAL: only a build time was measured, and no
budget was stated anywhere. This module measures, for the corpus the
deployment is pointed at:

* **build time** -- BM25 + vector + hybrid index over the loaded chunks;
* **size** -- the on-disk corpus artifacts (normalized chunk files, quality
  report) and the per-chunk text size, plus the index's own allocation
  footprint (``tracemalloc`` peak, which attributes exactly what the index
  allocates rather than the whole process RSS);
* **cold start** -- a fresh interpreter that imports the app, loads the corpus
  and builds the index, timed end to end in a subprocess, with a bare
  ``python -c pass`` baseline measured beside it so interpreter startup is
  visible instead of silently attributed to the index;
* **search latency** -- p50/p95 over the deterministic question mix.

The budget (A3-05's "stated budget") lives here as constants and is checked
per measurement: build under 120 s and search p95 under 1500 ms on the real
corpus. Exceeding a budget is a decision point (the pgvector/persistence
work), not a failure -- the report marks it, it does not throw.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

#: Stated budget (AUD-A1-22): the numbers that would trigger the deferred
#: pgvector/persistence work.
BUDGETS = {
    "build_seconds": 120.0,
    "search_p95_ms": 1500.0,
}

#: The same deterministic mix the stage harness uses, so a "search latency"
#: number means the same queries everywhere.
QUESTIONS = (
    "কোষ কী?",
    "সালোকসংশ্লেষণ কী?",
    "ভগ্নাংশ কী?",
    "নিউটনের প্রথম সূত্র কী?",
    "গতির প্রকারভেদ কী?",
    "পানিচক্র কী?",
)

_COLD_START_SNIPPET = """
import time
from pathlib import Path
started = time.perf_counter()
from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
from bangla_gpt_api.retrieval.embedding import HashingEmbedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
corpus = Path({corpus!r})
chunks = load_nctb_corpus(
    corpus / "normalized", quality_report_path=corpus / "quality_report.json"
)
index = HybridIndex(chunks, HashingEmbedder())
print(round((time.perf_counter() - started) * 1000, 3))
"""


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile, 3-decimal ms; 0.0 for an empty sample."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(min(int(len(ordered) * fraction), len(ordered) - 1), 0)
    return round(ordered[index], 3)


def _corpus_disk_bytes(corpus_root: Path) -> dict[str, Any]:
    """Bytes of the corpus artifacts the loader reads at boot."""
    normalized = corpus_root / "normalized"
    chunk_files = sorted(normalized.glob("*.chunks.jsonl")) if normalized.is_dir() else []
    quality = corpus_root / "quality_report.json"
    chunk_bytes = sum(path.stat().st_size for path in chunk_files)
    return {
        "normalized_chunk_file_bytes": chunk_bytes,
        "normalized_chunk_file_count": len(chunk_files),
        "quality_report_bytes": quality.stat().st_size if quality.is_file() else 0,
        "total_artifact_bytes": chunk_bytes + (quality.stat().st_size if quality.is_file() else 0),
    }


def measure_load_and_build(corpus_root: Path) -> dict[str, Any]:
    """Load the corpus and build the served index, timing and sizing each step.

    Two builds on purpose: ``tracemalloc`` tracks every allocation and slows
    the build several-fold, so the *timed* build runs without it and a second
    build measures the allocation footprint. Quoting the tracemalloc-slowed
    number as the build time was a measurement bug caught by this module's
    first run (347 s instead of the real number) -- the two passes make that
    class of error impossible to hide.
    """
    from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    started = time.perf_counter()
    chunks = load_nctb_corpus(
        corpus_root / "normalized", quality_report_path=corpus_root / "quality_report.json"
    )
    load_seconds = round(time.perf_counter() - started, 3)

    build_started = time.perf_counter()
    index = HybridIndex(chunks, HashingEmbedder())
    build_seconds = round(time.perf_counter() - build_started, 3)

    tracemalloc.start()
    HybridIndex(chunks, HashingEmbedder())
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    latencies: list[float] = []
    for question in QUESTIONS:
        started = time.perf_counter()
        index.search(question, class_level=6, top_k=3)
        latencies.append((time.perf_counter() - started) * 1000)

    text_bytes = sum(len(chunk.text.encode("utf-8")) for chunk in chunks)
    return {
        "chunks": len(chunks),
        "load_seconds": load_seconds,
        "build_seconds": build_seconds,
        "index_peak_alloc_mb": round(peak_bytes / (1024 * 1024), 2),
        "index_bytes_per_chunk": round(peak_bytes / len(chunks), 1) if chunks else 0.0,
        "mean_chunk_text_bytes": round(text_bytes / len(chunks), 1) if chunks else 0.0,
        "search_latency": {
            "n": len(latencies),
            "p50_ms": percentile(latencies, 0.5),
            "p95_ms": percentile(latencies, 0.95),
        },
        "within_budget": {
            "build_seconds": build_seconds <= BUDGETS["build_seconds"],
            "search_p95_ms": percentile(latencies, 0.95) <= BUDGETS["search_p95_ms"],
        },
        "definition": (
            "build_seconds is a clean build of BM25 + vector + hybrid; "
            "index_peak_alloc_mb is a SECOND build under tracemalloc (which "
            "slows the build, so its time is not reported)"
        ),
    }


def measure_cold_start(corpus_root: Path, *, timeout: float = 600.0) -> dict[str, Any]:
    """Fresh-interpreter cold start, with the bare interpreter baseline beside it.

    The baseline is what a process costs before it does any work; the cold
    start is that plus imports, corpus load and index build. Reporting both
    stops interpreter startup from being read as index cost.

    A child that fails is reported as ``status: failed`` with the value
    ``None`` -- its wall-clock time (a Python traceback is fast) must never be
    quoted as a cold start. That happened on this module's first run and the
    status field is the fix.
    """
    baseline = _run_child("pass", timeout=timeout)
    work = _run_child(_COLD_START_SNIPPET.format(corpus=corpus_root.as_posix()), timeout=timeout)
    failed = work.get("returncode") != 0 or work.get("stdout_ms") is None
    return {
        "status": "failed" if failed else "measured",
        "interpreter_baseline_ms": None if failed else baseline.get("wall_ms"),
        "cold_start_total_ms": None if failed else work.get("wall_ms"),
        "cold_start_work_ms": work.get("stdout_ms"),
        "definition": (
            "cold_start_total_ms = fresh `python -c` process wall time for "
            "imports + corpus load + index build; cold_start_work_ms is the "
            "in-child measurement of load+build only; interpreter_baseline_ms "
            "is `python -c pass` on the same machine. status=failed means the "
            "child process failed and every number beside it is null."
        ),
        "stderr_tail": work.get("stderr_tail"),
    }


def _run_child(snippet: str, *, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(  # noqa: S603 - a fixed `python -c` snippet from this module, never user input
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    wall_ms = round((time.perf_counter() - started) * 1000, 3)
    stdout = completed.stdout.strip()
    stdout_ms = None
    if completed.returncode == 0 and stdout:
        try:
            stdout_ms = float(stdout.splitlines()[-1])
        except ValueError:
            stdout_ms = None
    return {
        "wall_ms": wall_ms,
        "returncode": completed.returncode,
        "stdout_ms": stdout_ms,
        "stderr_tail": completed.stderr.strip()[-400:] or None,
    }


def build_report(*, corpus_root: Path) -> dict[str, Any]:
    """The A3-05 measurement block for one corpus root (fallback: sample corpus)."""
    corpus_label = f"nctb:{corpus_root}"
    if not (corpus_root / "normalized").is_dir():
        raise SystemExit(f"corpus not built at {corpus_root} -- run build_nctb_corpus.py first")
    report: dict[str, Any] = {
        "generated_by": "bangla_gpt_api.evaluation.index_budget",
        "run_conditions": {
            "host": platform.node(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "corpus": corpus_label,
            "note": "timings are host-dependent; the budget check is against the stated numbers",
        },
        "budgets": BUDGETS,
        "disk": _corpus_disk_bytes(corpus_root),
        "build": measure_load_and_build(corpus_root),
        "cold_start": measure_cold_start(corpus_root),
    }
    build: dict[str, Any] = report["build"]
    report["within_budget"] = {
        "build_seconds": build["within_budget"]["build_seconds"],
        "search_p95_ms": build["within_budget"]["search_p95_ms"],
    }
    return report


def markdown_summary(report: dict) -> str:
    """The measurement table for docs; generated, never hand-copied."""
    build = report["build"]
    cold = report["cold_start"]
    disk = report["disk"]
    cold_rows = (
        [
            f"| interpreter baseline | {cold['interpreter_baseline_ms']} ms | — | — |",
            f"| cold start (fresh process) | {cold['cold_start_total_ms']} ms | — | — |",
            f"| cold start (in-child load+build) | {cold['cold_start_work_ms']} ms | — | — |",
        ]
        if cold.get("status") == "measured"
        else [
            f"| cold start (fresh process) | not measured — child failed "
            f"({str(cold.get('stderr_tail') or '')[:60]}…) | — | — |"
        ]
    )
    rows = [
        "| Measurement | Value | Budget | Within |",
        "| --- | --- | --- | --- |",
        f"| corpus chunks | {build['chunks']} | — | — |",
        f"| corpus artifact bytes | {disk['total_artifact_bytes']} | — | — |",
        f"| mean chunk text bytes | {build['mean_chunk_text_bytes']} | — | — |",
        f"| corpus load | {build['load_seconds']} s | — | — |",
        f"| index build | {build['build_seconds']} s | {report['budgets']['build_seconds']} s | "
        f"{'yes' if build['within_budget']['build_seconds'] else 'NO'} |",
        f"| index peak allocation | {build['index_peak_alloc_mb']} MB | — | — |",
        f"| index allocation per chunk | {build['index_bytes_per_chunk']} B | — | — |",
        f"| search p50 | {build['search_latency']['p50_ms']} ms | — | — |",
        f"| search p95 | {build['search_latency']['p95_ms']} ms | "
        f"{report['budgets']['search_p95_ms']} ms | "
        f"{'yes' if build['within_budget']['search_p95_ms'] else 'NO'} |",
        *cold_rows,
    ]
    return "\n".join(rows)


__all__ = [
    "BUDGETS",
    "QUESTIONS",
    "build_report",
    "markdown_summary",
    "measure_cold_start",
    "measure_load_and_build",
    "percentile",
]


def load_artifact(path: Path) -> dict[str, Any]:
    """Read a previously written index-budget artifact (used by the docs test)."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data
