# One way to do each thing — the code-style register

Audit finding: **D-15** (one way to do each thing) — "HTTP client, date library,
state management, validation library, logging, ID generation, time source
(UTC), error type: mixed approaches are enumerated and unified." This file is
that enumeration, with the canonical choice per area and the measured
divergences. It is a register, not a style essay: a new divergence is a defect,
and this file is where it is written down.

Measured 2026-10-19 on branch `chore/enterprise-hardening-20261018` (working
tree; counts are from the commands recorded in `.audit/evidence/`).

## The canonical choices

| Concern | One way | Defined at | Second way seen today |
| --- | --- | --- | --- |
| Time source (Python) | the injectable clock seam: `db.clock.utcnow()` (naive UTC, the storage contract) and `Clock.now_aware()` when an aware value is needed | `apps/api/src/bangla_gpt_api/db/clock.py` | direct `datetime.now(UTC)` calls: 53 sites, migration tracked as AUD-EF-16 (the module docstring names the bulk migration of ~90 call sites) |
| Naive-UTC storage boundary | `db/types.py` normalizes every datetime column to naive UTC | `apps/api/src/bangla_gpt_api/db/types.py:54` | `datetime.now(UTC).replace(tzinfo=None)` written inline at 33 sites (`jobs.py:59`, `services/verification.py:41`, `services/govt_report.py:108`, ...) |
| Time source (web) | parse API timestamps only through `parseServerDate`; format through the same module's helpers | `apps/web/src/lib/datetime.ts` | none for API values; `new Date()` is used only for client-local instants (`offlineStore.ts:87`, copyright year) |
| HTTP client (Python) | `httpx` | `providers/gemini.py:23`, `providers/openai.py:25` | none — zero `requests` imports in `apps/api/src` |
| HTTP client (web) | the single wrapper in `api.ts` (`fetch` + token handling + timeouts) | `apps/web/src/api.ts:284` | `lib/apiProxy.ts:85` is node-side middleware code for the Vite dev/preview proxy, not app code |
| Validation | Pydantic v2 models for every request/response (154 `BaseModel` classes) | `apps/api/src/bangla_gpt_api/schemas/` and routers | none; rule logic that is not a schema (alignment, numeric checks) lives in explicit service functions that raise typed errors |
| State management (web) | react-query for all server state (`useQuery`/`useMutation`, 9 modules); `useState` for local UI; `AuthContext` for session | `apps/web/src/AuthContext.tsx`, pages | zero `useEffect`+`fetch` data paths |
| Logging | stdlib `logging` via `logging_config.py` helpers, one line per event | 43 modules call `logging.getLogger` | `print()` only in the evaluation CLI, its documented output contract |
| ID generation | integer autoincrement PKs for domain rows; `uuid4()` for the one UUID-keyed table and for internal correlation ids; `secrets.token_hex` for high-entropy codes (invite codes, token `jti`) | `db/models.py:41` (int PKs), `db/models.py:928` (UUID), `routers/parent.py:172`, `routers/admin.py:166` | request/trace ids generated twice (see below) |
| Error type (API) | `HTTPException` with the registered problem-details shape at the router boundary; `ProviderError` and the small custom hierarchy for provider/domain failures | `routers/common.py`, 166 `HTTPException(` raises | none at the boundary; the taxonomy itself is tracked as C-06 |
| Config | typed `Settings` (pydantic-settings) reading the environment; no direct `os.environ` reads in app code | `apps/api/src/bangla_gpt_api/config.py` | none |

## Divergences with file:line (the unification backlog)

1. **Correlation-id generation exists twice.** `middleware.py:68` builds
   `uuid.uuid4().hex[:16]` inline; `logging_config.new_trace_id()`
   (`logging_config.py:258`) builds the same value with a function-local
   `import uuid as _uuid`. Cheap unification: the middleware should call
   `new_trace_id()`. Owner: whoever next touches `middleware.py`.
2. **Inline naive-UTC conversions (33 sites).** The clock seam exists; the
   conversions are correct but repeated. This is the AUD-EF-16 migration; do
   not do it in bulk — migrate call sites as they are touched, as
   `db/clock.py` itself instructs. Sites observed: `jobs.py:59`,
   `services/verification.py:41`, `services/costs.py:110`,
   `services/govt_report.py:108`, and 29 more (see evidence).
3. **Direct `datetime.now(UTC)` (53 sites)** vs the clock seam — same backlog,
   not a correctness bug: the seam exists for testability at boundaries
   (`services/retention.py`, `services/parent_digest.py`, `services/mailer.py`
   already import it).
4. **Three import spellings of the same stdlib UUID call**:
   `from uuid import uuid4` (`db/models.py:2`), `uuid.uuid4` (`middleware.py`),
   `import uuid as _uuid` (`logging_config.py:258`). Follows from (1); one
   helper import in `logging_config.py` removes the third.

## Rules

- New code uses the canonical column; a deliberate exception needs a comment
  explaining what the canonical choice cannot do there.
- If a second approach is genuinely needed, it gets an ADR first, then a row in
  this table; otherwise reviewers ask for the canonical one.
- Counts in this file are measurements, not estimates; re-run the greps in
  `.audit/evidence/E-R2-d2-005-d15-one-way-audit.txt` before quoting them.
