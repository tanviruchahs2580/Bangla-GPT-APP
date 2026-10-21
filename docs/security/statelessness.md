# Statelessness posture (C-07)

What a second replica may and may not share, stated so the exception is
explicit rather than discovered. Verify method: **two-replica test**
(`apps/api/scripts/replica_check.py`, run in CI by the `replica-check` job and
locally by `cd apps/api && python scripts/replica_check.py`; last local run
`.audit/tmp/r3/replica_check.json`, evidence `E-R3-ws4-c07-replica`) plus the
job-ledger test `tests/test_h2_jobs_single_run.py` (two processes, one run).

## Shared state (cross-replica safe by construction)

| State | Where | Notes |
|---|---|---|
| Rate-limit counters | Redis when `RATE_LIMIT_BACKEND=redis` | boot guard refuses `memory` with `WEB_CONCURRENCY>1`; `RATE_LIMIT_FAIL_OPEN=false` fails closed |
| Auth deny-lists (logout `jti`, refresh family, impersonation) | shared cache | strict reads (fail closed) for impersonation and refresh rotation; the logout deny-list read is fail-soft with the TTL + password-epoch guarantees still in force |
| Dashboard/RAG caches | shared cache | keyed per user/tenant/query hash; a miss is always safe |
| Database | PostgreSQL (or a single-writer SQLite in single-worker deployments) | boot guard refuses file-SQLite with multiple workers |
| Scheduled jobs (digest, weakness rollup) | `JobRun` ledger in the DB | an atomic claim means N replicas run the job once |
| SSE | one response per connection, no cross-request state | proven through a proxy in the replica check |

## Per-process state, and why each is safe

- **Retrieval index**: each worker builds the in-memory corpus index at boot.
  The corpus artifact is identical across replicas (fingerprinted and
  versioned; see `docs/RAG_ARCHITECTURE.md` "known open items"), so the
  indexes are equivalent read-only copies -- memory cost is duplicated, not
  correctness. The replica check proves a RAG cache warmed on replica A is
  served by replica B.
- **AiJob execution is IN-PROCESS on every replica** (the documented
  exception to "no shared state in process memory"): content generation is
  dispatched with `asyncio.create_task` from the request that created the
  job, and the startup recovery loop re-dispatches jobs abandoned by a dead
  process. This is safe with N replicas because execution rights come from an
  **atomic database claim** (`services/ai_jobs.claim_ai_job` -- a single
  conditional UPDATE), not from process memory: two replicas that both see a
  pending job, and a recovery loop running on every replica, cannot run the
  same job twice. The claim is pinned by
  `apps/api/tests/test_h2_jobs_single_run.py`, and
  `apps/api/tests/test_r3_ws4_statelessness.py` pins that the recovery loop is
  armed regardless of `JOBS_BACKEND` (any replica may run it).
- **In-process scheduler loops** (parent digest, weakness rollup) run only
  when `JOBS_BACKEND=inline`; with `arq` the external worker owns the
  schedule. Either way the `JobRun` claim is the single-run guarantee, so
  running the loops on every web replica is safe.
- **The in-memory rate limiter/cache backends** exist for development and
  single-process deployments only; production boot refuses them with multiple
  workers (`_validate_rate_limit_redis`, pinned by
  `tests/test_production_guards.py` and re-pinned in
  `tests/test_r3_ws4_statelessness.py` together with the compose defaults that
  satisfy it).

Owner note: the replica check needs Docker (it starts a throwaway Redis) or
`--redis-url`; exit 3 (blocked) is a failure in CI, not a skip.
