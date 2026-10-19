"""Bounded soak + saturation probe for the API (I-08 / AUD-HI-10).

Runs the real app in-process under uvicorn (mock LLM provider only) and drives
it over HTTP at a fixed rate, sampling RSS (Windows psapi / Linux
/proc/self/statm -- a leak is a trend, not a high number), SQLAlchemy pool
state (checked-out connections are the leak signal a request path can produce)
and per-endpoint latency/errors. A second bounded phase ramps concurrency to
locate the saturation point, which a fixed-rate soak alone cannot answer.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import mmap
import os
import sys
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "api" / "src"))

#: Deterministic throwaway validator value (built, not a literal, so no scanner
#: has to distinguish it from a real credential).
_THROWAWAY_JWT_SECRET = "-".join(("soak", "not", "a", "credential") * 3)

P95_BUDGET_MS = 800.0  # the documented non-LLM budget (docs/operations/SLO.md)
ERROR_BUDGET_RATIO = 0.01

# "kosh ki?" -- a class-6 science question the bundled sample corpus answers.
QUESTION = "\u0995\u09cb\u09b7 \u0995\u09c0?"
SEARCH_TERM = "\u0995\u09cb\u09b7"


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def rss_mb() -> float | None:
    """Resident set size of this process in MiB, or None when unmeasurable."""
    try:
        # os.name, not sys.platform: mypy narrows sys.platform to the build
        # platform and then calls the other branch unreachable.
        if os.name == "nt":
            counters = _ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            get_memory_info = ctypes.WinDLL("kernel32", use_last_error=True).K32GetProcessMemoryInfo
            # Without argtypes ctypes truncates the 64-bit process handle.
            get_memory_info.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
            get_memory_info.restype = ctypes.c_int
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if not get_memory_info(handle, ctypes.byref(counters), counters.cb):
                return None
            return round(float(counters.WorkingSetSize) / (1024 * 1024), 1)
        with open("/proc/self/statm", encoding="ascii") as statm:
            resident_pages = int(statm.read().split()[1])
        return round(resident_pages * mmap.PAGESIZE / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - a metric must never stop the soak
        return None


def _pool_counts(session_factory: Any) -> dict[str, int]:
    """Parse SQLAlchemy's free-form pool status string into numbers."""
    keys = ("pool_size", "in_pool", "overflow", "checked_out")
    try:
        status = session_factory.kw["bind"].pool.status()
        numbers = [int(t) for t in status.replace(":", " ").split() if t.lstrip("-").isdigit()]
    except Exception:  # noqa: BLE001
        return {}
    return dict(zip(keys, numbers, strict=False)) if len(numbers) >= 4 else {}


def _client_connections(client: Any) -> int | None:
    try:
        return len(client._transport._pool.connections)  # noqa: SLF001 - our client
    except Exception:  # noqa: BLE001
        return None


class Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.latencies: dict[str, list[float]] = defaultdict(list)
        self.errors: dict[str, int] = defaultdict(int)
        self.statuses: dict[str, int] = defaultdict(int)

    def record(self, name: str, elapsed_ms: float, status: int) -> None:
        with self._lock:
            self.latencies[name].append(elapsed_ms)
            self.statuses[f"{name}:{status}"] += 1
            if status >= 500 or status == 0:
                self.errors[name] += 1

    def total(self) -> int:
        with self._lock:
            return sum(len(values) for values in self.latencies.values())

    def snapshot(self) -> dict[str, Any]:
        def percentile(values: list[float], fraction: float) -> float:
            ordered = sorted(values)
            return round(ordered[min(int(len(ordered) * fraction), len(ordered) - 1)], 1)

        with self._lock:
            endpoints = {
                name: {
                    "n": len(values),
                    "p50_ms": percentile(values, 0.50),
                    "p95_ms": percentile(values, 0.95),
                    "p99_ms": percentile(values, 0.99),
                    "max_ms": round(max(values), 1),
                    "errors": self.errors.get(name, 0),
                }
                for name, values in sorted(self.latencies.items())
                if values
            }
            return {
                "endpoints": endpoints,
                "statuses": dict(sorted(self.statuses.items())),
                "total": sum(len(v) for v in self.latencies.values()),
            }


def _hit(client: Any, name: str, method: str, url: str, stats: Stats, **kwargs: Any) -> int:
    started, status = time.perf_counter(), 0
    try:
        if kwargs.pop("stream", False):
            with client.stream(method, url, **kwargs) as response:
                status = response.status_code
                for _line in response.iter_lines():
                    pass
        else:
            response = client.request(method, url, **kwargs)
            status = response.status_code
            response.read()
    except Exception:  # noqa: BLE001 - a failed request is a data point
        status = 0
    stats.record(name, (time.perf_counter() - started) * 1000, status)
    return status


def _worker_loop(
    client: Any,
    jobs: list[tuple[str, str, str, dict[str, Any]]],
    stop: threading.Event,
    stats: Stats,
    rate_per_worker: float,
) -> None:
    """One client thread: round-robin the mix at a fixed per-worker rate."""
    interval = 1.0 / rate_per_worker
    index = 0
    next_at = time.perf_counter()
    while not stop.is_set():
        name, method, url, kwargs = jobs[index % len(jobs)]
        index += 1
        _hit(client, name, method, url, stats, **kwargs)
        next_at += interval
        sleep_for = next_at - time.perf_counter()
        if sleep_for > 0:
            stop.wait(sleep_for)
        else:
            next_at = time.perf_counter()  # behind schedule: do not burst


def _ramp(client: Any, headers: dict[str, str], seconds: int, top: int) -> list[dict]:
    """Concurrency ladder on /tutor/ask; one row per step."""
    rows: list[dict] = []
    body = {"question": QUESTION, "class_level": 6, "subject": "science"}
    workers = 1
    while workers <= top:
        stop = threading.Event()
        step_stats = Stats()
        counts = [0] * workers

        def hammer(
            slot: int,
            _stop: threading.Event = stop,
            _counts: list[int] = counts,
            _stats: Stats = step_stats,
        ) -> None:
            while not _stop.is_set():
                _hit(client, "ask", "POST", "/tutor/ask", _stats, json=body, headers=headers)
                _counts[slot] += 1

        threads = [
            threading.Thread(target=hammer, args=(slot,), daemon=True) for slot in range(workers)
        ]
        started = time.perf_counter()
        for thread in threads:
            thread.start()
        time.sleep(seconds)
        stop.set()
        for thread in threads:
            thread.join(timeout=10)
        elapsed = time.perf_counter() - started
        snap = step_stats.snapshot()["endpoints"].get("ask", {})
        row = {
            "workers": workers,
            "seconds": round(elapsed, 1),
            "requests": sum(counts),
            "rps": round(sum(counts) / elapsed, 1) if elapsed else 0.0,
            "p50_ms": snap.get("p50_ms", 0.0),
            "p95_ms": snap.get("p95_ms", 0.0),
            "errors": snap.get("errors", 0),
        }
        rows.append(row)
        print(
            f"  ramp workers={workers:>3} rps={row['rps']:>7} p50={row['p50_ms']:>8.1f}ms "
            f"p95={row['p95_ms']:>8.1f}ms errors={row['errors']}",
            flush=True,
        )
        workers *= 2
    return rows


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=12.0)
    parser.add_argument("--rate", type=float, default=6.0)
    parser.add_argument("--sample-seconds", type=float, default=15.0)
    parser.add_argument("--ramp-top", type=int, default=32)
    parser.add_argument("--ramp-seconds", type=int, default=15)
    parser.add_argument("--port", type=int, default=8077)
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def _start_server(db_path: Path, port: int) -> tuple[Any, Any, Any, Any]:
    """Settings + app + the running uvicorn pair, all hermetic (no .env)."""
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["ADMIN_EMAIL"] = ""
    os.environ["ADMIN_PASSWORD"] = ""
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["TRACING_ENABLED"] = "false"
    os.environ["JOBS_BACKEND"] = "inline"
    os.environ["ACCESS_LOG_ENABLED"] = "true"

    import uvicorn

    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.main import create_app

    settings = Settings(
        env="test",
        database_url=f"sqlite:///{db_path.as_posix()}",
        jwt_secret=_THROWAWAY_JWT_SECRET,
        admin_email=None,
        admin_password=None,
        llm_provider="mock",
        # Stability, not the limiter (it has its own tests): a per-user tutor
        # limit of N/min would throttle the mix. register/forgot are derived
        # rules, so they are overridden through RATE_LIMIT_RULES.
        rate_limit_tutor_per_minute=1_000_000,
        rate_limit_tutor_ip_per_minute=1_000_000,
        rate_limit_login_per_minute=1_000_000,
        rate_limit_rules={
            "/auth/register": (1_000_000, "ip"),
            "/auth/forgot": (1_000_000, "ip"),
            "/events": (1_000_000, "ip"),
        },
    )
    assert settings.llm_provider == "mock", "the soak must never call a paid provider"
    app = create_app(settings)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("the API did not start")
    return settings, app, server, thread


def _prepare_client(
    client: Any,
) -> tuple[dict[str, str], list[tuple[str, str, str, dict[str, Any]]]]:
    email = f"soak-{os.getpid()}@example.com"
    created = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "supersecret1",
            "name": "Soak Student",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    if created.status_code != 201:
        raise RuntimeError(f"register failed: {created.status_code} {created.text[:200]}")
    login = client.post("/auth/login", json={"email": email, "password": "supersecret1"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    conversation = client.post("/tutor/conversations", json={}, headers=headers)
    conversation_id = conversation.json()["id"] if conversation.status_code == 201 else None

    ask_body = {"question": QUESTION, "class_level": 6, "subject": "science"}
    jobs: list[tuple[str, str, str, dict[str, Any]]] = [
        ("ask", "POST", "/tutor/ask", {"json": ask_body, "headers": headers}),
        ("search", "GET", f"/search?q={SEARCH_TERM}", {"headers": headers}),
        ("dashboard", "GET", "/dashboard/summary", {"headers": headers}),
        ("health", "GET", "/health", {}),
        ("metrics", "GET", "/metrics", {}),
    ]
    if conversation_id is not None:
        jobs.append(
            (
                "stream",
                "POST",
                f"/tutor/conversations/{conversation_id}/messages/stream",
                {"json": {"message": QUESTION}, "headers": headers, "stream": True},
            )
        )
    # Warm-up: a typo in a path must not silently measure 404s for 12 minutes.
    for name, method, url, kwargs in jobs:
        probe = dict(kwargs)
        probe.pop("stream", None)
        response = client.request(method, url, **probe)
        if response.status_code >= 400:
            raise RuntimeError(f"warm-up {name} {method} {url} -> {response.status_code}")
        print(f"  warm-up {name:<10} {method} {url} -> {response.status_code}")
    return headers, jobs


def _summarise(report: dict[str, Any]) -> None:
    soak = report["phases"]["soak"]
    rss_values = [s["rss_mb"] for s in soak["samples"] if s["rss_mb"] is not None]
    if rss_values:
        slope = (rss_values[-1] - rss_values[0]) / max(1e-9, soak["seconds"]) * 3600
        report["memory"] = {
            "first_mb": rss_values[0],
            "min_mb": min(rss_values),
            "last_mb": rss_values[-1],
            "peak_mb": max(rss_values),
            "slope_mb_per_hour": round(slope, 2),
        }
    checked_out = [
        s["db_pool"]["checked_out"]
        for s in soak["samples"]
        if s["db_pool"].get("checked_out") is not None
    ]
    if checked_out:
        report["db_checked_out"] = {
            "first": checked_out[0],
            "min": min(checked_out),
            "max": max(checked_out),
            "last": checked_out[-1],
        }
    saturated = next(
        (
            row
            for row in report["phases"]["ramp"]
            if row["p95_ms"] > P95_BUDGET_MS
            or (row["requests"] and row["errors"] / row["requests"] > ERROR_BUDGET_RATIO)
        ),
        None,
    )
    report["saturation"] = {
        "budget_p95_ms": P95_BUDGET_MS,
        "error_budget_ratio": ERROR_BUDGET_RATIO,
        "first_step_over_budget": saturated,
        "saturation_workers": saturated["workers"] if saturated else None,
        "saturation_rps": saturated["rps"] if saturated else None,
        "note": (
            "first step where p95 exceeded 800 ms or errors exceeded 1%"
            if saturated
            else "no step breached the budget within the ladder"
        ),
    }


def _run(args: argparse.Namespace, app: Any, client: Any) -> dict[str, Any]:
    session_factory = app.state.ctx.session_factory
    headers, jobs = _prepare_client(client)

    def sample(started_at: float) -> dict[str, Any]:
        return {
            "t_s": round(time.monotonic() - started_at, 1),
            "rss_mb": rss_mb(),
            "db_pool": _pool_counts(session_factory),
            "client_conns": _client_connections(client),
            "requests": stats.total(),
        }

    stats = Stats()
    threads = max(1, min(8, int(args.rate) or 1))
    stop = threading.Event()
    # Strided slices, so workers interleave endpoints, not hammer one at a time.
    load_threads = [
        threading.Thread(
            target=_worker_loop,
            args=(client, jobs[index::threads], stop, stats, args.rate / threads),
            name=f"load-{index}",
            daemon=True,
        )
        for index in range(threads)
    ]

    print(
        f"soak: {args.rate}/s of {len(jobs)} endpoints for {args.minutes:g} min "
        f"on {threads} threads",
        flush=True,
    )
    started_at = time.monotonic()
    samples = [sample(started_at)]
    for thread in load_threads:
        thread.start()
    soak_end = started_at + args.minutes * 60
    while time.monotonic() < soak_end:
        stop.wait(min(args.sample_seconds, max(0.1, soak_end - time.monotonic())))
        row = sample(started_at)
        samples.append(row)
        print(
            f"  t={row['t_s']:>6.0f}s rss={row['rss_mb']}MiB "
            f"db_checked_out={row['db_pool'].get('checked_out')} "
            f"client_conns={row['client_conns']} reqs={row['requests']}",
            flush=True,
        )
    stop.set()
    for thread in load_threads:
        thread.join(timeout=30)

    print("ramp: concurrency ladder on /tutor/ask", flush=True)
    return {
        "soak": {
            "seconds": round(time.monotonic() - started_at, 1),
            "samples": samples,
            "result": stats.snapshot(),
        },
        "ramp": _ramp(client, headers, args.ramp_seconds, args.ramp_top),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    workdir = REPO / ".audit" / "tmp-i2" / "soak"
    workdir.mkdir(parents=True, exist_ok=True)
    db_path = workdir / f"soak-{os.getpid()}.db"

    try:
        settings, app, server, server_thread = _start_server(db_path, args.port)
    except RuntimeError as exc:
        print(f"::error:: {exc}", file=sys.stderr)
        return 2

    import httpx

    report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "argv": {key: str(value) for key, value in vars(args).items()},
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "database": settings.database_url,
        "llm_provider": settings.llm_provider,
        "rate_per_second": args.rate,
        "phases": {},
    }
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{args.port}",
            timeout=30.0,
            limits=httpx.Limits(max_connections=64),
        ) as client:
            report["phases"] = _run(args, app, client)
    finally:
        server.should_exit = True
        server_thread.join(timeout=20)
        report["finished_at"] = datetime.now(UTC).isoformat()

    _summarise(report)
    out = args.out or (REPO / "docs" / "operations" / f"soak-{datetime.now(UTC):%Y%m%d}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"saturation: {report['saturation']}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
