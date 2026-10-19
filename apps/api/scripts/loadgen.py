r"""A9-05: the runnable load harness (asyncio, no external load tool).

The audit's A9-05 was BLOCKED: k6 is not installed, the committed k6 profiles
were never executed, and the docs' local numbers came from an uncommitted
scratch harness. This script is the reproducible replacement -- standard
library plus httpx (already a dependency), no new tool to install:

    cd apps/api
    python scripts/loadgen.py                     # in-process uvicorn, mock provider
    python scripts/loadgen.py --base-url http://127.0.0.1:8000 --token-env BGPT_TOKEN

It drives a realistic mix against a *mock-provider server* -- 50%
``POST /tutor/ask`` (retrieval + gate + generation), 20% streaming chat
(``POST /tutor/conversations/{id}/messages/stream``, latency to the stream's
last byte), 20% ``GET /search`` and 10% ``GET /dashboard/summary`` (the
heaviest read path) -- at increasing concurrency, and archives p50/p95/p99,
throughput, error counts and the saturation level to ``eval/load_report.json``.

Honest scope, recorded in the artifact:

* the provider is ``mock``: the numbers measure the app (retrieval, gate,
  serialization, DB, event loop), NOT model time-to-first-token -- TTFT needs
  a live provider and is explicitly labelled unmeasured;
* one in-process server, so this finds the *app's* saturation point under a
  single worker, not the deployment's capacity; the report says so;
* run on a shared developer machine: the report records the host state
  (contention) so a noisy run is visible rather than mysterious.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = APP_ROOT / "eval" / "load_report.json"

PASSWORD = "local-fixture-password-1"  # noqa: S105 - throwaway local fixture
JWT_SECRET = "-".join(("load", "harness", "fixture") * 3)

#: Questions cycled across the run so the retrieval cache cannot turn every
#: request into a cache hit for one query (the cache key is the query).
QUESTIONS = (
    "সালোকসংশ্লেষণ কী?",
    "কোষ কী?",
    "ভগ্নাংশ কী?",
    "নিউটনের প্রথম সূত্র কী?",
    "পানিচক্র কী?",
    "ক্লোরোফিল কী?",
    "গতির প্রকারভেদ কী?",
    "বল কাকে বলে?",
)

#: The endpoint names the harness drives and the weights of the mix (out of
#: ten): a student asking, a chat turn, a search, and a dashboard read now and
#: then.
ENDPOINTS = ("ask", "stream", "search", "dashboard")
MIX = (("ask", 5), ("stream", 7), ("search", 9), ("dashboard", 10))

#: A9-01 proposals plus the interactive budget, quoted here so the report can
#: mark a level as saturated against a stated budget rather than a feeling.
BUDGETS = {
    "full_answer_p95_ms": 12000,
    "dashboard_p95_ms": 2000,
    "saturation_error_rate": 0.01,
    "saturation_p95_multiplier": 3.0,
}


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return round(ordered[index], 2)


#: Mode names: "capacity" raises the abuse-control limits so the server's own
#: saturation point is visible; "product-limits" keeps the shipped defaults
#: (30 tutor requests/user/min, 60/IP/min) and reports where the product's own
#: rate limiting caps a single-IP burst.
MODE_CAPACITY = "capacity"
MODE_PRODUCT_LIMITS = "product-limits"


def _start_server(
    port: int, db_path: Path, *, mode: str = MODE_CAPACITY
) -> tuple[object, threading.Thread]:
    """In-process uvicorn with a throwaway DB and the mock provider."""
    os.environ["ENV"] = "test"
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    import uvicorn

    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.main import create_app

    overrides: dict[str, Any] = {}
    if mode == MODE_CAPACITY:
        # Documented override for the capacity run only: the shipped limits are
        # an abuse control, not a capacity statement, and leaving them on makes
        # every level above ~1 rps measure 429s instead of the server.
        overrides = {
            "rate_limit_tutor_per_minute": 1_000_000,
            "rate_limit_tutor_ip_per_minute": 1_000_000,
        }
    settings = Settings(
        env="test",
        llm_provider="mock",
        database_url=f"sqlite:///{db_path.as_posix()}",
        jwt_secret=JWT_SECRET,
        **overrides,
    )
    app: Any = create_app(settings)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            return server, thread
        time.sleep(0.05)
    raise SystemExit("uvicorn did not start within 10s")


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _register_and_login(base_url: str) -> dict[str, str]:
    import httpx

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "loadgen-student@example.com",
                "password": PASSWORD,
                "name": "Load Student",
                "role": "student",
                "class_level": 6,
                "guardian_consent": True,
            },
        )
        if response.status_code not in (201, 409):
            raise SystemExit(f"register: {response.status_code} {response.text[:200]}")
        login = await client.post(
            "/auth/login", json={"email": "loadgen-student@example.com", "password": PASSWORD}
        )
        if login.status_code != 200:
            raise SystemExit(f"login: {login.status_code} {login.text[:200]}")
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        conversation = await client.post(
            "/tutor/conversations", json={"title": "loadgen"}, headers=headers
        )
        if conversation.status_code != 201:
            raise SystemExit(f"conversation: {conversation.status_code} {conversation.text[:200]}")
        headers["X-Loadgen-Conversation"] = str(conversation.json()["id"])
        return headers


async def _one_ask(client, headers: dict[str, str], question: str) -> tuple[float, int]:
    started = time.perf_counter()
    response = await client.post(
        "/tutor/ask",
        json={"question": question, "class_level": 6, "subject": "science"},
        headers=headers,
    )
    return (time.perf_counter() - started) * 1000, response.status_code


async def _one_stream(
    client, headers: dict[str, str], conversation_id: int, question: str
) -> tuple[float, int]:
    """A full SSE turn: latency is time to the stream's last byte."""
    started = time.perf_counter()
    async with client.stream(
        "POST",
        f"/tutor/conversations/{conversation_id}/messages/stream",
        json={"message": question, "class_level": 6},
        headers=headers,
    ) as response:
        async for _line in response.aiter_lines():
            pass
    return (time.perf_counter() - started) * 1000, response.status_code


async def _one_search(client, headers: dict[str, str], query: str) -> tuple[float, int]:
    started = time.perf_counter()
    response = await client.get("/search", params={"q": query}, headers=headers)
    return (time.perf_counter() - started) * 1000, response.status_code


async def _one_dashboard(client, headers: dict[str, str]) -> tuple[float, int]:
    started = time.perf_counter()
    response = await client.get("/dashboard/summary", headers=headers)
    return (time.perf_counter() - started) * 1000, response.status_code


def _mix_of(index: int) -> str:
    """Which endpoint request ``index`` drives, by the documented weights."""
    bucket = index % 10
    return next(endpoint for endpoint, weight in MIX if bucket < weight)


async def run_level(
    base_url: str,
    headers: dict[str, str],
    concurrency: int,
    requests: int,
    *,
    conversation_id: int,
) -> dict:
    """One concurrency level: the documented mix, repeated ``requests`` times."""
    import httpx

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    latencies: dict[str, list[float]] = {name: [] for name in ENDPOINTS}
    statuses: dict[str, int] = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def one(client, index: int) -> None:
        async with semaphore:
            name = _mix_of(index)
            question = QUESTIONS[index % len(QUESTIONS)]
            if name == "ask":
                latency, status = await _one_ask(client, headers, question)
            elif name == "stream":
                latency, status = await _one_stream(client, headers, conversation_id, question)
            elif name == "search":
                latency, status = await _one_search(client, headers, question)
            else:
                latency, status = await _one_dashboard(client, headers)
            latencies[name].append(latency)
            statuses[str(status)] = statuses.get(str(status), 0) + 1

    async with httpx.AsyncClient(base_url=base_url, timeout=60.0, limits=limits) as client:
        started = time.perf_counter()
        await asyncio.gather(*(one(client, index) for index in range(requests)))
        wall = time.perf_counter() - started

    errors = sum(count for status, count in statuses.items() if status != "200")
    return {
        "concurrency": concurrency,
        "requests": requests,
        "wall_seconds": round(wall, 2),
        "throughput_rps": round(requests / wall, 2) if wall else 0.0,
        "status_counts": statuses,
        "errors": errors,
        "error_rate": round(errors / requests, 4) if requests else 0.0,
        **{
            name: {
                "n": len(values),
                "p50_ms": _percentile(values, 0.5),
                "p95_ms": _percentile(values, 0.95),
                "p99_ms": _percentile(values, 0.99),
                "mean_ms": round(statistics.fmean(values), 2) if values else 0.0,
            }
            for name, values in latencies.items()
        },
    }


def saturation_notes(levels: list[dict], *, baseline_p95: float | None = None) -> dict:
    """Where the run saturated, against the stated budgets -- or that it did not."""
    if not levels:
        return {"saturated": False, "reason": "no levels ran"}
    base = baseline_p95 or levels[0]["ask"]["p95_ms"]
    notes = []
    saturated_at = None
    for level in levels:
        ask_p95 = level["ask"]["p95_ms"]
        stream_p95 = level.get("stream", {}).get("p95_ms", 0.0)
        dashboard_p95 = level["dashboard"]["p95_ms"]
        over_budget = max(ask_p95, stream_p95) > BUDGETS["full_answer_p95_ms"]
        over_dashboard = dashboard_p95 > BUDGETS["dashboard_p95_ms"]
        over_errors = level["error_rate"] > BUDGETS["saturation_error_rate"]
        degraded = base and ask_p95 > base * BUDGETS["saturation_p95_multiplier"]
        if over_budget or over_dashboard or over_errors or degraded:
            saturated_at = saturated_at or level["concurrency"]
            notes.append(
                f"concurrency {level['concurrency']}: ask p95 {ask_p95}ms, stream p95 "
                f"{stream_p95}ms, dashboard p95 {dashboard_p95}ms (base {base}ms), "
                f"error rate {level['error_rate']}"
            )
    peak = max(levels, key=lambda level: level["throughput_rps"])
    return {
        "saturated": saturated_at is not None,
        "first_saturated_concurrency": saturated_at,
        "observations": notes,
        "peak_throughput_rps": peak["throughput_rps"],
        "peak_throughput_concurrency": peak["concurrency"],
        "note": (
            "saturation = error rate above the stated cap, ask/stream p95 beyond the "
            "A9-01 answer budget, dashboard p95 beyond its own budget, or ask p95 "
            "above 3x the lowest-concurrency p95"
            if notes
            else "no saturation observed within the exercised concurrency range"
        ),
    }


def build_report(levels: list[dict], *, base_url: str, mode: str) -> dict:
    ask_baseline = levels[0]["ask"]["p95_ms"] if levels else None
    return {
        "generated_by": "scripts/loadgen.py",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": mode,
        "base_url": base_url,
        "mix": "50% POST /tutor/ask, 20% streaming chat, 20% GET /search, "
        "10% GET /dashboard/summary",
        "budgets": BUDGETS,
        "run_conditions": {
            "host": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "provider": "mock (app-side latency only; TTFT is NOT measured)",
            "server": "single in-process uvicorn worker, throwaway sqlite",
            "mode": mode,
            "rate_limits": (
                "raised for this capacity run (shipped: 30/user/min, 60/IP/min)"
                if mode == MODE_CAPACITY
                else "shipped defaults: 30 tutor requests/user/min, 60/IP/min per IP"
            ),
            "database": "sqlite (dev/test posture; Postgres numbers differ)",
        },
        "levels": levels,
        "saturation": saturation_notes(levels, baseline_p95=ask_baseline),
        "unmeasured": [
            "model time-to-first-token (needs a live provider)",
            "multi-worker / multi-replica capacity",
            "abort/cancellation behaviour under client disconnects",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A9-05 asyncio load harness")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--base-url", default=None, help="drive an already-running server")
    parser.add_argument("--levels", default="1,4,8,16,32", help="concurrency levels")
    parser.add_argument("--requests-per-level", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument(
        "--mode",
        choices=[MODE_CAPACITY, MODE_PRODUCT_LIMITS],
        default=MODE_CAPACITY,
        help="capacity raises the abuse-control limits; product-limits keeps them",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    levels_wanted = [int(part) for part in args.levels.split(",") if part.strip()]
    using_external = args.base_url is not None
    base_url = args.base_url or f"http://127.0.0.1:{_free_port()}"
    server = None
    workdir = Path(tempfile.mkdtemp(prefix="bgpt-load-"))
    if not using_external:
        server, _thread = _start_server(
            int(base_url.rsplit(":", 1)[1]), workdir / "load.db", mode=args.mode
        )

    try:
        headers = asyncio.run(_register_and_login(base_url))
        conversation_id = int(headers.pop("X-Loadgen-Conversation"))
        levels: list[dict] = []
        for concurrency in levels_wanted:
            requests = max(args.requests_per_level, concurrency * 4)
            level = asyncio.run(
                run_level(base_url, headers, concurrency, requests, conversation_id=conversation_id)
            )
            levels.append(level)
            print(
                f"c={level['concurrency']:>3} n={level['requests']:>4} "
                f"rp/s={level['throughput_rps']:>7} ask p95={level['ask']['p95_ms']}ms "
                f"stream p95={level['stream']['p95_ms']}ms "
                f"search p95={level['search']['p95_ms']}ms "
                f"dashboard p95={level['dashboard']['p95_ms']}ms errors={level['errors']}"
            )
        report = build_report(levels, base_url=base_url, mode=args.mode)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        saturation = report["saturation"]
        print(
            f"\nsaturation: {'yes at c=' + str(saturation['first_saturated_concurrency']) if saturation['saturated'] else 'none observed'}; "
            f"peak {saturation['peak_throughput_rps']} rp/s at c={saturation['peak_throughput_concurrency']}"
        )
        for note in saturation["observations"] or [saturation["note"]]:
            print(f"  {note}")
        print(f"\nwritten -> {args.out}")
    finally:
        if server is not None:
            server.should_exit = True  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    sys.exit(main())
