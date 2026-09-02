"""Concurrency probe (B16 companion when k6 is unavailable).

Runs a mixed workload (70% authenticated tutor asks / 30% health+profile
reads) at increasing concurrency levels and reports throughput, p50/p95
latency and error rate per level.

Usage:
    python scripts/concurrency_probe.py [BASE_URL] [--levels 1,5,10] [--reqs 40]
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    index = min(len(sorted_values) - 1, max(0, round(pct / 100 * len(sorted_values)) - 1))
    return sorted_values[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", nargs="?", default="http://127.0.0.1:8000")
    parser.add_argument("--levels", default="1,5,10,20")
    parser.add_argument("--reqs", type=int, default=40)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    levels = [int(x) for x in args.levels.split(",")]

    email = f"probe-{time.time_ns()}@example.com"
    with httpx.Client(base_url=base, timeout=20.0) as client:
        register = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "probe-pass-123",
                "name": "প্রোব",
                "role": "student",
                "class_level": 6,
                "guardian_consent": True,
            },
        )
        assert register.status_code == 201, register.text
        login = client.post("/auth/login", json={"email": email, "password": "probe-pass-123"})
        token = login.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

    def one_request(call: httpx.Client, is_ask: bool) -> tuple[bool, float]:
        start = time.perf_counter()
        try:
            if is_ask:
                response = call.post(
                    "/tutor/ask",
                    headers=auth_headers,
                    json={"question": "কোষ কী?", "class_level": 6, "subject": "science"},
                )
            else:
                response = call.get("/health")
            ok = response.status_code < 400
        except httpx.HTTPError:
            ok = False
        return ok, time.perf_counter() - start

    print(f"target={base} reqs_per_level={args.reqs}")
    print(f"{'concurrency':>12} {'err%':>7} {'p50_ms':>8} {'p95_ms':>8} {'rps':>7}")
    summary: list[dict] = []
    for level in levels:
        results: list[tuple[bool, float]] = []
        with (
            httpx.Client(base_url=base, timeout=30.0) as client,
            ThreadPoolExecutor(max_workers=level) as pool,
        ):
            started = time.perf_counter()
            futures = [
                pool.submit(one_request, client, i % 10 < 7)
                for i in range(args.reqs)
            ]
            for future in futures:
                results.append(future.result())
            wall = time.perf_counter() - started
        latencies = sorted(lat for _, lat in results)
        errors = sum(1 for ok, _ in results if not ok)
        row = {
            "concurrency": level,
            "error_pct": round(100.0 * errors / len(results), 2),
            "p50_ms": round(percentile(latencies, 50) * 1000, 1),
            "p95_ms": round(percentile(latencies, 95) * 1000, 1),
            "rps": round(len(results) / wall, 1),
        }
        summary.append(row)
        print(
            f"{row['concurrency']:>12} {row['error_pct']:>7} "
            f"{row['p50_ms']:>8} {row['p95_ms']:>8} {row['rps']:>7}"
        )

    Path_like = sys.stdout
    Path_like.write(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
