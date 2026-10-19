# Load harness (A9-05)

Command: `cd apps/api && python scripts/loadgen.py [--mode capacity|product-limits]`.
Artifacts: `apps/api/eval/load_report.json` (capacity mode) and
`apps/api/eval/load_report_limits.json` (shipped rate limits).
Tests: `apps/api/tests/test_eval2_loadgen.py`.

k6 is not installed in this environment, so the harness is a small asyncio
generator using httpx (already a runtime dependency) — reproducible from a
clean checkout with no new tool. It starts a single in-process uvicorn worker
on a throwaway SQLite database with the mock provider, registers a student,
creates one conversation, then drives a realistic mix — **50%
`POST /tutor/ask`, 20% streaming chat
(`POST /tutor/conversations/{id}/messages/stream`, latency to the stream's last
byte), 20% `GET /search`, 10% `GET /dashboard/summary`** — at increasing
concurrency, and archives p50/p95/p99, throughput, error counts and the
saturation level.

## Measured on 2026-10-19 (Windows 11 developer host, Python 3.12.10, mock provider)

Capacity mode (abuse-control limits raised; documented in the artifact):

| Concurrency | Requests | req/s | ask p95 | stream p95 | search p95 | dashboard p95 | errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 50 | 17.4 | 59 ms | 92 ms | 266 ms | 31 ms | 0 |
| 4 | 50 | 17.1 | 443 ms | 530 ms | 418 ms | 374 ms | 0 |
| 8 | 50 | 14.8 | 827 ms | 952 ms | 660 ms | 1116 ms | 0 |
| 16 | 64 | 12.2 | 2005 ms | 2610 ms | 2174 ms | 1443 ms | 0 |
| 32 | 128 | 9.7 | 6384 ms | 6498 ms | 5174 ms | 5744 ms | 0 |

Product-limits mode (shipped defaults: 30 tutor requests/user/min, 60/IP/min):

| Concurrency | Requests | req/s | ask p95 | stream p95 | search p95 | errors |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 40 | 16.3 | 87 ms | 93 ms | 252 ms | 0 |
| 4 | 40 | 19.4 | 421 ms | 466 ms | 391 ms | 10 (25%) |

## Saturation notes

- **The product's own rate limiting is the first ceiling.** With the shipped
  limits a single IP is clean for one 40-request burst (p95 87 ms on `/tutor/ask`)
  and starts receiving 429s in the next one (25% at concurrency 4). That is the
  abuse control working as designed; it also means a single-IP client cannot
  exceed roughly one `/tutor/ask` per second, whatever the hardware can do.
- **App-side capacity saturates around concurrency 4-8.** Throughput peaks at
  ~17 req/s at concurrency 1 and falls monotonically (17.1 → 14.8 → 12.2 → 9.7)
  while p95 climbs from 59 ms to 6.4 s — a queueing knee on one event loop, not
  a failure: zero errors at every level, and p95 stays inside the A9-01 answer
  budget (12 s) even at concurrency 32. The `search` lane tracks `ask`, which
  is expected: both drive the same CPU-bound retrieval scan.
- The harness's saturation flag fires at concurrency 4 by its 3x-p95 rule;
  read that as "the knee is here", not as "the service is broken".

## What this does not measure

- **Model time-to-first-token and full-answer latency for a live model.** The
  provider is mock; the numbers above are app-side (retrieval, gate, DB,
  serialization, event loop). TTFT needs a live provider and is labelled
  unmeasured in the artifact.
- **Multi-worker/multi-replica capacity.** One in-process worker by design.
  Two-replica behaviour of counters, caches, SSE and job queues remains a
  separate question (AUD-A2-10).
- **Client-disconnect cancellation.** The streaming lane reads each stream to
  completion; abort behaviour is not exercised here.
- Numbers come from a shared developer machine; the artifact records host,
  platform and CPU count so a contended run is visible. Re-run before quoting
  them for capacity planning.

## Owner actions

1. Re-run against a staging deployment (`--base-url`) with a live provider to
   get TTFT and true answer latency.
2. Record the deployment's own saturation point before any capacity promise;
   this harness is the instrument, not the answer.
