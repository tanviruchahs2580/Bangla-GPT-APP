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

## Stage-level latency and TTFT (A9-01)

Command: `cd apps/api && python -m bangla_gpt_api.evaluation.cli --stage-latency --out eval/tmp/stage_latency.json`.
Artifact: `apps/api/eval/stage_latency.json`. Harness:
`bangla_gpt_api/evaluation/stage_latency.py` (instance-method wrappers around
the real `TutorService`; no service code changes). Tests:
`apps/api/tests/test_eval3_stage_latency.py`.

The harness runs the pipeline at a **stated concurrency** (default levels 1
and 8, 30 iterations each, streaming at level 1) and reports p50/p95/p99 per
stage. Measured on 2026-10-19 (Windows 11 developer host, Python 3.12.10,
sample corpus 78 chunks, **mock provider**):

| Level | Stage | n | p50 ms | p95 ms | p99 ms |
| --- | --- | --- | --- | --- | --- |
| c1 ask | query_processing (measured remainder) | 30 | 2.38 | 4.02 | 9.42 |
| c1 ask | retrieval | 30 | 11.42 | 15.92 | 57.39 |
| c1 ask | — of which rerank (sub-stage) | 30 | 4.32 | 6.56 | 7.62 |
| c1 ask | context_build | 25 | 0.23 | 0.41 | 0.97 |
| c1 ask | provider_select | 25 | 0.01 | 0.01 | 0.01 |
| c1 ask | llm_total | 25 | 0.24 | 0.78 | 46.06 |
| c1 ask | post_process | 25 | 2.51 | 3.68 | 4.47 |
| c1 ask | **full answer** | 30 | 16.41 | 21.64 | 118.33 |
| c8 ask | retrieval | 30 | 98.42 | 144.34 | 152.99 |
| c8 ask | **full answer** | 30 | 105.23 | 150.07 | 153.43 |
| c1 stream | retrieval | 30 | 10.20 | 14.27 | 19.97 |
| c1 stream | **llm_ttft** | 30 | 11.30 | 15.13 | 20.93 |
| c1 stream | llm_total | 30 | 13.91 | 19.67 | 23.35 |
| c1 stream | **full answer** | 30 | 13.91 | 19.67 | 23.35 |

Budget checks against the A9-01 proposals (recorded in the artifact):

| Level | retrieval p95 (≤ 300 ms) | TTFT p95 (≤ 3 s) | full answer p95 (≤ 12 s) |
| --- | --- | --- | --- |
| c1 ask | 15.92 ✓ | n/a (no first token on the non-streaming path) | 21.64 ✓ |
| c8 ask | 144.34 ✓ | n/a | 150.07 ✓ |
| c1 stream | 14.27 ✓ | 15.13 ✓ | 19.67 ✓ |

Reading the numbers honestly:

- `llm_ttft` here is **pipeline time-to-first-token with the mock provider**
  (the mock streams its answer in 48-character chunks), so it measures the
  app's path to the first SSE token — not model latency. The live-model TTFT
  remains the owner-run measurement; this harness removes the app-side
  unknown from it.
- A stage the request's path does not exercise is **omitted** (`n = 0`), never
  reported as 0 ms: the ask path has no TTFT, the stream path never calls
  `_assemble`. The aggregate filters on which stages the request measured.
- Only 25 of 30 asks carry the post-retrieval stages: 5 questions were
  refused by the grounding gate, which is the pipeline working as designed.
- Concurrency 8 costs roughly 7x the c1 retrieval p50 (11 → 98 ms): search is
  CPU work offloaded to a thread, so parallel asks queue for CPU. At 78 chunks
  that is invisible against the budgets; on the real corpus see
  `eval/index_budget.json` and `docs/operations/SOAK.md`.
- `query_processing` is the measured remainder (wall minus instrumented
  stages): normalization, safety screen, follow-up condensation and response
  plumbing. A new stage added to the service is absorbed there rather than
  silently attributed to another stage.

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
