# S5.5 — Scale audit + load test (2026-09-07)

**Target (master prompt):** pagination/N+1 audit; k6: 500 RPS read, 50 RPS
write, p95 < 400 ms on **non-AI** endpoints. PASS = targets met **on staging**
+ this report saved. k6 is not installed on this machine, so the k6 script is
a deliverable and the local numbers below come from an equivalent Python
harness (`apps/api/_s55_load.py`, scratch).

## 1. Pagination / N+1 audit

Full-codebase audit of every list/hot path in `apps/api/src/bangla_gpt_api/main.py`.
Fixes were kept **response-shape-preserving** (defaults return everything the
old code returned; caps only bind at the documented limit) so no client breaks.

### Fixed (pinned by `apps/api/tests/test_scale_v2.py`, 5 tests)

| Path | Before | After |
| --- | --- | --- |
| `GET /teacher/students` roster briefs | 1 + N `COUNT/AVG` queries on `quiz_attempts` | chunked (500) single `GROUP BY` query; `limit` param (1–1000). Test proves **exactly 1** `quiz_attempts` statement for 4 students and identical values incl. NULL-score rows |
| `GET /tutor/conversations` | 1 + N message counts | single `GROUP BY` count per page (incl. empty conversations) |
| `GET /tutor/conversations/{id}/messages` | unbounded (every message ever) | `limit` param (default 200, max 500); newest-N fetched, returned chronological |
| `GET /assignments/mine` | full `assignments` table scan + 1 attempt fetch per match | window over newest N (`limit`, default 200) + single batched attempt fetch. Window semantics documented: `limit` windows the *scan*, not the returned page (proper fix = membership link table, §3) |
| `GET /teacher/assignments/{id}/progress` | 1 + 2N lookups | 2 batched `IN` queries |
| `GET /teacher/qpapers` | unbounded | `limit`/`offset` (default 100, max 200) |
| `GET /teacher/shorttests`, `GET /shorttests/mine` | unbounded | `limit`/`offset` params |

### Documented, not changed (each with rationale)

- `GET /admin/content/versions` (A8): admin-only, low QPS; full payload pull is
  acceptable at current corpus size. Cap when content service grows.
- Admin school-stats overview (B5): N+1 across schools, but school count is
  dozens at most; SQL `COUNT` rewrite when it grows.
- `POST /admin/classrooms/import` (B6): one existence `SELECT` per CSV row —
  admin batch path, bounded by file upload size limit.
- Quiz submit hot path (B7/B8): a few primary-key `db.get` lookups per submit;
  PK hits, cheap.
- Admin analytics / school overview aggregate views load rows then aggregate
  in Python; correct for now, `SQL COUNT`-native versions are the upgrade path.
- Dashboard `/progress` scans `AnswerLog` via ORM rows (cached 60 s, S5.3) —
  move to SQL aggregate + Redis when row counts climb.
- `Assignment.attempts` JSON membership forces a scan; a link table
  (`assignment_students`) is the proper fix, deliberately deferred (schema +
  migration + backfill for one admin-scale query).

## 2. Load test

### Deliverable: `scripts/load/k6_scale.js`

- Reads: constant-arrival 500 req/s over `/dashboard/summary` (40 %), `/search`
  (25 %), `/revision/due` (20 %), `/health` (15 %) — all non-AI.
- Writes: constant-arrival 50 req/s of `POST /learn/progress` (DB upsert).
  `POST /events` is **excluded**: its by-design 60/min/IP limiter was observed
  answering 429 from a single generator IP, so including it would measure the
  limiter, not the API.
- Thresholds (PASS-WHEN): `http_req_duration{mix:read} p(95)<400`,
  same for `{mix:write}`, `http_req_failed rate<0.01`.
- `setup()` logs in **once** (login is limited to 10/min by design) and reuses
  the JWT; run against staging with pre-provisioned throwaway student creds:
  `k6 run -e BASE_URL=https://STAGING -e LOAD_EMAIL=... -e LOAD_PASSWORD=... scripts/load/k6_scale.js`

**Staging run is a 🖐 step**: staging URL/credentials are human-provided.
For an infra-only pass, start staging API with `PROVIDER=mock`.

### Local numbers (honest): single laptop, Windows, SQLite, uvicorn

Closed-loop ladder (`_s55_load.py`), same mixes minus `/events`, one student
token, warm caches:

| workers | conc | achieved RPS | p50 ms | p95 ms | p99 ms | err % |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 14.1 | 12.9 | 75.9 | 75.9 | 0 |
| 1 | 8 | 41.2 | 63.3 | 91.5 | 119.9 | 0 |
| 1 | 16 | 40.8 | 105.5 | 204.6 | 317.4 | 0 |
| 1 | 32 | 47.7 | 249.3 | 412.0 | 463.6 | 2.9 (429 /events) |
| 4 | 8 | 59.3 | 20.5 | 67.1 | 157.5 | 0 |
| 4 | 16 | 60.8 | 26.9 | 106.9 | 241.4 | 0 |
| 4 | 32 | 74.5 | 40.0 | 172.8 | 295.5 | 6.5 (429 /events) |
| 4 | 64 | 70.7 | 73.7 | 466.5 | 820.4 | 10.0 (429 /events) |

Reads of `/health`/`/dashboard`/`/search` stayed ~single-digit ms through the
ladder; the p95 climb at high concurrency is dominated by the SQLite write
path (`/learn/progress`) plus local harness contention.

**Open-loop attempt at the staging target on this machine (550 req/s for
10 s): failed loudly** — ~34 RPS achieved, p50 ~15 s, 78 % client-side
connection errors; the generator saturated the laptop (Windows ephemeral
ports + Python threads) and the server needed a restart. A single-process
SQLite dev box cannot serve 500 RPS; that is exactly why the PASS gate is
staging (Postgres + N API replicas + Caddy + Redis caches).

### Verdict

- **Local: PASS for the audit half** (unbounded reads capped, N+1s batched,
  pinned by tests; 4-worker box holds p95 < 400 ms up to ~75 RPS on this mix).
- **500/50 RPS @ p95<400 ms: NOT met locally and not claimable locally** —
  measurement environment is one laptop + SQLite. The k6 script + staging
  instructions above are the ready-made gate; run when staging creds exist 🖐.

## 3. Upgrade path (in priority order)

1. Staging k6 run (script ready) → tune `--workers`/replicas until read p95 <
   400 ms at 500 RPS; Postgres removes the write-side ceiling.
2. `assignment_students` link table (replaces JSON-membership scan).
3. SQL-native aggregates for admin analytics + `/progress` (drop Python row
   scans once AnswerLog/attempt tables grow).
4. Cursor pagination if offset-based paging shows skip/drift at scale.
