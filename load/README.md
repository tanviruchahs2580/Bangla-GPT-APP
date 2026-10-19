# Load, soak and benchmark profiles

> **Execution status in the audited revision: NOT RUN.** The audit environment
> had no `k6` binary (recorded in the evidence bundle), so everything in this
> directory is a committed, reviewable *procedure* — never a measurement. Do
> not cite numbers from it until a run is archived next to it. The
> `apps/api/scripts/bench_dashboards.py` benchmark *did* run (SQLite, 100k
> rows); its recorded output is `docs/operations/bench-dashboards-100k.json`.

## What is here

| File | Purpose | Thresholds it enforces |
|---|---|---|
| `k6-tutor.js` | Small smoke of the tutor path (pre-existing) | error < 1%, p95 < 800 ms |
| `tutor_load.js` | Mixed tutor/quiz/progress profile (pre-existing) | per-kind p95 gates |
| `k6-dashboards.js` | **New (I-07):** dashboard, content and search hot paths — where N+1 and missing-index problems live | dashboards p95 < 800 ms, content < 400 ms, search < 600 ms, tutor control path < 8000 ms, errors < 1% |
| `k6-soak.js` | **New (I-08):** 30–60 min steady-state soak of the streaming path | read p95 < 500 ms / p99 < 1500 ms, stream p95 < 15 s, error < 1%, throughput floor (`http_reqs rate > 0.1`) so a stalled run cannot "pass" |
| `../apps/api/scripts/bench_dashboards.py` | **New (H-06):** seeded 100k-row benchmark that records per-endpoint SQL statement counts | assertions live in `apps/api/tests/test_hi_dashboard_queries.py` |

## Running the load profiles

```bash
# Start the API on a machine you are allowed to load (staging, not production).
k6 run -e BASE_URL=http://127.0.0.1:8000 -e VUS=25 -e DURATION=3m load/k6-dashboards.js
k6 run -e BASE_URL=http://127.0.0.1:8000 -e VUS=10 -e DURATION=45m load/k6-soak.js
```

Preconditions, spelled out because a failed precondition looks like a product
defect in the summary:

- The dashboards profile needs a teacher account that sees data. Create one,
  register a classroom for the default school and enrol a few students
  (`apps/api/scripts/bench_dashboards.py` seeds exactly this shape if you point
  it at the same database).
- With `LLM_PROVIDER=mock` the tutor path is fast and deterministic — good for
  the *mechanism*; a live provider adds the real latency distribution and burns
  real budget (owner approval, `LIVE_LLM_EVAL_BUDGET_USD`).
- SSE responses hold the connection open; the soak profile sets a 120 s client
  timeout on purpose. A shorter timeout reports "errors" that are just the
  client giving up on a working stream.

## Recording a soak (half the evidence is outside k6)

k6 cannot see process memory or connection counts; those are the leak signals a
soak exists to find. Run these next to it and archive the outputs together:

```bash
# container-level memory/CPU/connection drift, 30 s interval
docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' >> soak-stats.log
# postgres connection count (if Postgres is in use)
docker compose exec -T postgres psql -U "$POSTGRES_USER" -c \
  "select count(*), state from pg_stat_activity group by state;" >> soak-stats.log
# API-side counters before and after
curl -s localhost:8000/metrics | grep -E 'bgpt_http_requests_total|bgpt_rag_' > soak-metrics-before.txt
```

Then attach `soak-stats.log` to the run and compare:
`process_resident_memory_bytes` (or `docker stats` memory) should be flat, the
Postgres `state='idle'` count should return to the pool size, and
`http_req_duration` p95 should not drift upward across the run.

Archive a run as `docs/operations/soak-<YYYY-MM-DD>.md` (results, host, build
SHA, thresholds pass/fail) and update `docs/operations/SLO.md` §5 — an
unarchived run is not evidence (T7).

## What these profiles do not cover

- Browser-side performance (the SPA) — that is Lighthouse/web-vitals territory,
  recorded on the frontend side.
- Multi-replica behaviour (rate-limit counters, SSE behind a proxy, caches) —
  needs the two-replica test, not a k6 profile.
- Provider-side rate limits and quota — only a live-key run shows those.
