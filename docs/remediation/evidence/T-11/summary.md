# T-11 summary — authorization matrix

Executed 2026-11-19 at `3ee0ae9`+ (branch `remediation/0.2.0`).

## What was built
1. **Checked-in machine-readable classification** — `apps/api/tests/data/route_classification.json`: 141 operations (140 OpenAPI + the runtime-only `/metrics`), each with class (`public` 12 / `authenticated` 54 / `role-restricted` 74 / `production-token-gated` 1), allowed roles, owned params, handler. Generated from the routers' AST (`docs/remediation/tools/t11_classify.py`) and hand-verified against `routers/deps.py` aliases (`CurrentUser`, `TeacherOrAdminUser`, `AdminUser`, `SchoolStaffUser`, `ParentUser`, `AIGenerationUser`→`require_ai_budget`→`TeacherOrAdminUser` + AI budget).
2. **Guard tests** — `apps/api/tests/test_route_classification.py` (5 tests): file covers exactly the served operations (missing = fail, stale = fail); classes validated; public set cross-checked against `main.PUBLIC_OPERATIONS`; `/metrics` pinned as the only production-token-gated op.
3. **Matrix additions** — `apps/api/tests/test_authz_matrix.py` (202 tests, all passing): mass-assignment on registration (extra `school_id`/`email_verified`/`totp_secret`/`token_epoch` ignored; role Literal blocks `admin` self-grant with 422 and no row), `email_verified` proven a server decision (auth.py:220) not client input; cross-tenant classroom WRITE refused (403/404) with positive control; unauthenticated sweep over every authenticated/role-restricted GET (exact 401) and every authenticated/role-restricted operation (never 2xx anonymously) — 128 parametrized cases driven from the classification file.

## Result
**202 matrix + guard tests green; 0 leaks found** — no BC-3 fixes were required (the existing per-handler guards held). Combined run with the pre-existing tenancy suites: `evidence/T-11/t11-matrix-and-guard.txt`.

## Deliberately cross-tenant routes
`/health`, `/live`, `/ready`, `/status` (public probes, booleans only — `PUBLIC_OPERATIONS`), `/metrics` (production-token-gated), `/openapi.json` + docs routes (non-production only, main.py:771). Recorded in the classification file.

## Notes
- Runtime-only `/metrics` (F-30) is IN the file; the OpenAPI-only comparison would have missed it.
- CI runs the matrix in the default job; the Postgres job's full domain suite includes it via the standard suite (T-16 wiring).
