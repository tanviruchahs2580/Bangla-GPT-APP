# API versioning and deprecation policy

The API is served unversioned at the root (`/auth/login`, `/tutor/...`). This
page states what that means for callers and when that changes (F-064, API-02),
so a breaking change has a written migration path instead of a surprise.

## What is promised today

- **Additive within the current surface.** New routes, new optional request
  fields and new response fields may ship at any time. Clients must ignore
  unknown response fields; the web client already does (it reads named fields,
  never object shapes).
- **No removals or renames without the process below.** A route, a required
  field, a field type or an error code that clients branch on is a contract.
- **Error envelope.** Business errors answer `{"detail": {"code","message"}}`;
  the guard path answers the same coded shape with `unauthenticated` /
  `insufficient_role` (F-067). `code` is the stable part; `message` is copy.
- **Timestamps** are ISO-8601 UTC with a `Z` suffix, on every response (F-063).
- **Rate-limited responses** carry `Retry-After` in seconds (F-062).

## Deprecation process

1. Announce in `CHANGELOG.md` and mark the operation `deprecated: true` in its
   OpenAPI definition, naming the replacement in the description.
2. Serve the operation for at least **one minor release and no fewer than 90
   days** after the announcement, answering with both headers:
   - `Deprecation: @<unix-seconds-when-announced>` (RFC 9745)
   - `Sunset: <HTTP-date of the removal>` (RFC 8594)
3. Remove it only after the window, in the same release that drops it from
   `docs/route_baseline.md` (regenerated from `app.openapi()`).
4. If a caller cannot migrate, the replacement ships first and the old route
   keeps working until the owner signs off; there is no "big-bang" cutover.

## When a `/v1` prefix lands

The prefix is introduced only together with a genuinely incompatible change
(for example a different session or tenancy model). At that moment:

- the current root surface becomes `/v1` and keeps working for the deprecation
  window;
- `docs/route_baseline.md` records both surfaces;
- the CI route-diff step (see below) fails if a removal appears in the baseline
  without a matching deprecation entry.

There is deliberately no `/v0` or date-based prefix today: an unversioned
surface with a documented additive-only rule is easier to keep honest than a
version number nobody revs.

## Guards that keep this true

- `apps/api/tests/test_openapi_contract.py` - every operation has a tag,
  summary, operationId and documented error bodies.
- `apps/api/tests/test_openapi_auth_matrix.py` - the 12 public operations in
  the spec equal the 12 declared public operations.
- `docs/route_baseline.md`, regenerated from the app's own schema, is the
  inventory a reviewer diffs a route change against.
- Breaking-change detection at field level (`oasdiff`) is the recorded
  follow-up: the tool is not installed in CI today, so the route-level diff is
  the enforced part.
