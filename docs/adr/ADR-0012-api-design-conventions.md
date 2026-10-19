# ADR-0012: API design conventions (pagination, versioning, error shape, idempotency)

Status: Accepted (2026-10-19). Recorded as a standalone file by the R3 audit
round for C-10 (API design consistency), H-03 (HTTP semantics) and C-06
(error shape); the consolidated log `docs/adr/ADRs.md` covers ADR-0001..0010.
Template and tone follow that log.

## Context

The audit read the served OpenAPI document and found four distinct problems,
all verified by execution rather than by inspection:

1. **Pagination was ad hoc.** Streams/routes declared `limit` with hand-written
   `Query` bounds, defaults of 20/50/100/200/500 and caps of 50..1000; some
   collections had no `offset` at all. A client could neither discover the cap
   nor walk a long collection.
2. **No versioning or deprecation policy existed.** The OpenAPI document
   carries `info.version` (0.9.2), but nothing said what a version means, what
   may change without one, or how a breaking change is announced.
3. **Two error envelopes existed on the wire.** HTTPExceptions and 422s
   rendered as RFC 9457 `application/problem+json` (C-06, additively, `detail`
   preserved), while the rate limiter and the body-size guard -- both
   middleware, not exceptions -- returned a bare `{"detail": ...}` as
   `application/json`. The 500 handler was a third variant. A client needed a
   content-type switch to parse an error.
4. **No idempotency or optimistic concurrency existed**: `rg Idempotency-Key`
   and `rg If-Match` returned zero hits, so a client that retried a POST could
   repeat a side effect (and could never recover a response it lost), and two
   concurrent PATCHes to the same resource silently lost one edit.

## Decision

### Pagination (C-10)

One module owns the convention: `apps/api/src/bangla_gpt_api/routers/_pagination.py`.
Every collection GET takes its window through a named preset rather than a
hand-written `Query` literal:

| Preset | Default | Cap | Use |
|---|---|---|---|
| `ArchivePage` | 50 | 200 | archives and search-style lists (`/notes`) |
| `TaskListPage` | 100 | 200 | the SPA's one-call task lists and teacher lists |
| `WindowPage` | 200 | 200 | endpoints that scan a recent window before filtering in Python (`/assignments/mine`) |

Rules that hold for every collection endpoint:

* `limit` is `ge=1` with a maximum -- no endpoint is unbounded;
* `offset` is `ge=0`, defaults to 0, and is applied after an explicit stable
  sort (`created_at DESC, id DESC` or an equivalent unique tiebreak);
* filters are typed and validated by the request contract, not parsed by hand.

Documented exceptions (pinned by
`tests/test_r3_ws3_pagination_convention.py`):

* **Top-N queue** -- `GET /revision/due` has no `offset` on purpose: it answers
  "what is due now" and reports `due_count` separately; paging a due queue is
  meaningless.
* **Tracked deviations owned by other file sets** (fixed by their owners, the
  test refuses any *new* deviation):
  * `GET /teacher/students` (routers/teacher.py): cap 1000, no offset;
  * `GET /teacher/documents` (routers/teacher_content.py): no offset;
  * `GET /tutor/conversations/{id}/messages` (routers/tutor.py): cap 500, no
    offset.

`WindowPage` endpoints must say so in their docstring: `offset` there walks
the *candidate window*, because membership filtering happens after the slice,
so a page can legitimately return fewer rows than `limit` while matches exist
further back. `GET /assignments/mine` documents this inline; the proper fix is
the membership link table already tracked as a gap.

### Versioning and deprecation (C-10)

* **The OpenAPI document is the contract.** `docs/API.md` is generated from it
  (`apps/api/scripts/gen_api_docs.py`, which the path guard verifies and which
  is run from `apps/api`; drift is checked in CI by
  `tests/test_hi_api_docs.py`);
  `info.version` is the API version and is bumped per release.
* **No URL version prefix today**, deliberately. The single first-party client
  (the SPA) ships from this repository and is deployed with the API, so the
  consumer population that URL-versioning protects does not exist
  (`docs/hosting_decision.md`). A `/v2` prefix will be introduced at the first
  breaking change, not pre-emptively.
* **Within the current line, changes must be additive**: new optional fields,
  new endpoints, new response members. `detail` in errors may gain members but
  never lose or rename one (the C-06 rule).
* **A breaking change requires, in one change set**: a new path or a new
  version prefix, a migration note in `CHANGELOG.md`, and the old path marked
  `deprecated=True` in FastAPI (so both the served OpenAPI and `/docs` show
  it) for at least one release before removal.
* Removal is announced in `CHANGELOG.md` and the `docs/API.md` entry is
  regenerated in the removing commit.

### One error shape (C-06 / C-10)

Every error response -- from a route, a dependency, FastAPI's validation, the
exception handlers, the rate limiter, the body-size guard and the 500 handler
-- is `application/problem+json` with `type`, `title`, `status`, `instance`
and `detail`, where `detail` is byte-identical to the pre-RFC body (a string,
`{code, message}`, or the validation list). Business-rule codes are catalogued
in `routers/_error_contract.py::ERROR_CATALOG` and the catalog is scanned
against the source by `tests/test_cd_error_contract.py`.

### Idempotency and optimistic concurrency (H-03)

`apps/api/src/bangla_gpt_api/routers/_http_semantics.py` provides both, opt-in:

* **`Idempotency-Key`** on a creating POST (`POST /teacher/classrooms/{id}/import-file`).
  The key is claimed atomically in the shared cache (`set_json_nx_strict`, the
  same primitive as refresh-token rotation), scoped by route + user id and
  hashed before use. A duplicate while the first call runs gets
  `409 idempotency_in_progress`; a duplicate afterwards gets the stored
  status/body with `Idempotent-Replay: true`; 4xx failures are replayed too, a
  5xx or 429 leaves a 60-second claim so an immediate retry cannot duplicate a
  partially-committed side effect; a cache outage fails **open** (the request
  proceeds) because a dedupe cache must not become a write outage.
* **`ETag` / `If-Match`** on the read-modify-write PATCH
  (`GET`/`PATCH /students/me/prefs`). The GET serves a strong content-hash
  validator; a PATCH presenting a stale one gets `412 precondition_failed`
  and changes nothing; omitting `If-Match` keeps the legacy last-write-wins
  behaviour so no existing client breaks.

Both are declared in the route signatures, so they appear in the served
OpenAPI document.

## Alternatives Considered

1. **URL versioning from day one** (`/v1/...`) -- rejected: one first-party
   client, no external consumers; the prefix would be ceremony, and the cost
   (every route, every doc, every test) buys nothing today. The policy above
   defers it to the first breaking change.
2. **A global pagination middleware rewriting `limit`** -- rejected: caps and
   offsets must be visible in the OpenAPI contract a client reads, not applied
   invisibly at the edge.
3. **Cursor pagination everywhere** -- rejected for now: no measured need; the
   collections are small and offset + stable sort is correct and simpler. A
   cursor can be added additively later without breaking the offset contract.
4. **Idempotency middleware capturing and replaying every POST** -- rejected:
   it would cache responses for endpoints with no duplicate-side-effect risk
   (costs storage), and it makes the behaviour invisible to the OpenAPI
   contract. Opt-in per route documents itself.
5. **Failing closed when the idempotency cache is down** -- rejected: the rate
   limiter already fails closed for abuse control; a broken cache should not
   also refuse every classroom import. The trade-off (a retry during an outage
   can duplicate) is documented on the helper.

## Consequences

- **+** A client can page every collection, bounded by a documented cap, and
  can parse every error with one content-type branch.
- **+** Retrying the CSV import is safe and recovers the one-time invite codes.
- **+** Concurrent preference edits are detectable instead of silently lost.
- **-** Three pagination presets and three tracked deviations require upkeep;
  the convention test fails on any *new* deviation, so the list cannot grow
  silently.
- **-** `_http_semantics` depends on the shared cache being configured; the
  fail-open branch is tested directly (a stub cache raising `CacheUnavailable`).
- **-** The versioning policy is a commitment to run `/v2` at the first
  breaking change; owners must treat "additive only" as binding.
