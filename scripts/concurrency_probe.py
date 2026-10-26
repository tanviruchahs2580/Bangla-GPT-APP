"""Concurrency probe (B16 companion when k6 is unavailable).

Runs a mixed workload (70% authenticated tutor asks / 30% health+profile
reads) at increasing concurrency levels and reports throughput, p50/p95
latency and error rate per level.

A production-strict stack (ENV=production/staging) refuses to log in an
unverified account, so registering a throwaway one is not enough there: pass
``--mailpit`` to complete the email verification from a Mailpit instance, or
``--email``/``--password`` to reuse an account that is already verified.

Usage:
    python scripts/concurrency_probe.py [BASE_URL] [--levels 1,5,10] [--reqs 40]
    python scripts/concurrency_probe.py https://staging.example.com         --mailpit http://127.0.0.1:8025
    python scripts/concurrency_probe.py https://staging.example.com         --email loadtest@example.com --password '...'
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
    index = min(
        len(sorted_values) - 1, max(0, round(pct / 100 * len(sorted_values)) - 1)
    )
    return sorted_values[index]


def _verification_token(mailpit: str, email: str, timeout: float = 20.0) -> str:
    """Read the verification token for `email` out of a Mailpit instance.

    Production-strict environments require a verified address before login, and
    the verification mail lands in the stack's own Mailpit. Polling it here is
    what makes this probe usable against staging instead of only against a dev
    environment that auto-verifies.
    """
    import re

    base = mailpit.rstrip("/")
    deadline = time.monotonic() + timeout
    pattern = re.compile(r"[A-Za-z0-9_-]{20,}")
    while time.monotonic() < deadline:
        listing = httpx.get(f"{base}/api/v1/messages", timeout=10.0).json()
        for message in listing.get("messages", []):
            if email not in [to["Address"] for to in message.get("To", [])]:
                continue
            detail = httpx.get(
                f"{base}/api/v1/message/{message['ID']}", timeout=10.0
            ).json()
            hit = pattern.findall(detail.get("Text") or "")
            if hit:
                return hit[0]
        time.sleep(1.0)
    raise AssertionError(
        f"no verification email for {email} arrived within {timeout:.0f}s"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", nargs="?", default="http://127.0.0.1:8000")
    parser.add_argument("--levels", default="1,5,10,20")
    parser.add_argument("--reqs", type=int, default=40)
    parser.add_argument(
        "--email",
        default=None,
        help="reuse an existing (already verified) account instead of registering one",
    )
    parser.add_argument("--password", default="probe-pass-123")
    parser.add_argument(
        "--mailpit",
        default=None,
        help="Mailpit base URL (e.g. http://127.0.0.1:8025): verify the fresh account",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    levels = [int(x) for x in args.levels.split(",")]

    email = args.email or f"probe-{time.time_ns()}@example.com"
    password = args.password
    with httpx.Client(base_url=base, timeout=20.0) as client:
        if args.email is None:
            register = client.post(
                "/auth/register",
                json={
                    "email": email,
                    "password": password,
                    "name": "প্রোব",
                    "role": "student",
                    "class_level": 6,
                    "guardian_consent": True,
                },
            )
            assert register.status_code == 201, register.text
            if args.mailpit:
                verify_token = _verification_token(args.mailpit, email)
                verified = client.post(
                    "/auth/verify-email", json={"token": verify_token}
                )
                assert verified.status_code == 200, verified.text
        login = client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, (
            f"login failed for {email}: {login.status_code} {login.text}"
            + (
                ""
                if args.email
                else "  (a production-strict stack needs --mailpit or --email)"
            )
        )
        token = login.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

    def one_request(call: httpx.Client, is_ask: bool) -> tuple[bool, float]:
        start = time.perf_counter()
        try:
            if is_ask:
                response = call.post(
                    "/tutor/ask",
                    headers=auth_headers,
                    json={
                        "question": "কোষ কী?",
                        "class_level": 6,
                        "subject": "science",
                    },
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
                pool.submit(one_request, client, i % 10 < 7) for i in range(args.reqs)
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
