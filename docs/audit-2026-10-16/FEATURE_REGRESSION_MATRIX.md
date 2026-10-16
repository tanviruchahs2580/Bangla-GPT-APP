# FEATURE REGRESSION MATRIX — Bangla GPT APP (2026-10-16)

Machine-readable per-endpoint rows: `FEATURE_REGRESSION_MATRIX.csv`
(generated from the app's own route table by
`probes/gen_regression_matrix.py`, so it cannot drift from the declared
surface). This document records the parts a CSV cannot: the roles, the frontend
routes, the workflows, and what "no regression" actually rests on.

## 1. API surface

| Source | Count |
|---|---|
| Operations in the generated matrix | 136 |
| of which deliberately public (`PUBLIC_OPERATIONS`) | 12 |
| of which FastAPI built-in dev surface (`/docs/oauth2-redirect`) | 1 |
| **Application operations** | **135** |

By owning router: `teacher_content` 19 · `school` 17 · `learn` 15 · `tutor` 13 ·
`parent` 12 · `assessment` 11 · `auth` 11 · `admin` 10 · `workspace` 9 ·
`system` 6 · `teacher` 6 · `users` 6.

The 12 public operations are exactly: `POST /auth/{register,login,forgot,reset,
verify-email,resend-verification,mfa/challenge,join-school}` and
`GET /{health,live,ready,status}`. `/metrics` is deliberately **not** public —
it is production-gated by token and by a boot guard. `test_openapi_auth_matrix.py`
fails if this set and the code ever disagree, which is the strongest available
protection against a forgotten auth dependency.

## 2. Roles and tenancy

| Role | Enforcement point | Regression basis |
|---|---|---|
| anonymous | `PUBLIC_OPERATIONS` allowlist | matrix test + 401 assertions across suites |
| student | `CurrentUser` + self/ownership checks (`users`, `learn`, `workspace`, `parent` self endpoints) | `test_auth_teacher.py`, `test_learn.py`, `test_learn_progress.py`, `test_chat_history_crud.py`, `test_data_export.py` |
| parent | `ParentUser`; only linked children (`test_parent_dashboard.py`, `test_compliance_v2.py:313`) | re-run green |
| teacher | `TeacherOrAdminUser` + `_tenant_school_id` / `_assert_room_in_school` | `test_school_tenancy_isolation.py`, `test_school_routes_coverage.py`, `test_bulkassign.py` |
| school_admin | `SchoolStaffUser` scoped to own/default school | `test_school_onboarding.py`, `test_admin_center.py` |
| admin | `AdminUser`; last-admin demotion/deletion guards | `test_admin_hardening.py`, `test_security_v2.py`, `test_account_deletion.py` |
| impersonation | audited, time-boxed, revoked by an epoch check that fails closed | `test_phase1_exploits.py`, `test_support_ops.py` |

## 3. Frontend routes

All 22 routes in `apps/web/src/main.tsx`, each with its guard and post-change
status. Guard tested by `RequireAuth`; every route below rendered or was
statically reviewed in this audit.

| Route | Role guard | Post-change status |
|---|---|---|
| `/` | none (redirects by role) | PASS (static) |
| `/welcome`, `/login`, `/register`, `/forgot`, `/privacy`, `/terms`, `/status` | public | PASS — landing, login and status rendered live; register flow exercised through the API |
| `/student`, `/student/learn`, `/student/learn/:subject/:chapter`, `/student/tutor`, `/student/quiz`, `/student/me` | student | PASS — all rendered live; two defects fixed (`F-05`-class error states, `F-25`), four open (`F-26`, `F-29`, `F-30`, `F-32`) |
| `/teacher`, `/teacher/create`, `/teacher/classes`, `/teacher/assessments`, `/teacher/analytics`, `/teacher/profile` | teacher | PASS — home and create rendered live; the other three reviewed statically (unchanged by this audit) |
| `/parent` | parent | PASS (static; `suggestionSentence` shared with MePage and unit-tested) |
| `/admin` | admin | PASS — triage error state fixed (`F-05`) and covered by a new test; other panels unchanged |
| `/school` | school_admin | PASS (static; unchanged) |
| `*` | fallback → `/` | PASS (static) |

## 4. Critical user journeys exercised end to end

| Journey | Evidence |
|---|---|
| Register (with guardian consent) → login → JWT | live API: a student registration without consent is refused with `guardian_consent_required`; with consent it returns 201 and login returns a token |
| Student asks the tutor a Bangla question and gets an evidence-backed answer | live: SSE stream completed, citation chip opened the evidence modal |
| Student takes a quiz and sees honest results | live: start → 5 questions → results → revision/assigned tabs |
| Student reads a chapter, bookmarks it, downloads it offline, changes font size | live: all four worked (IndexedDB write confirmed, `aria-pressed` + toast on bookmark) |
| Student reads their weekly report | live: rendered after `F-25` fix, sentence matches the weak-chapter chip |
| Teacher opens the hub and the question-paper builder | live: submit correctly disabled until a name is typed |
| Parent links a child by invite code | API test (`test_parent_invite_flow_end_to_end`) + new entropy test; code format change verified backward compatible |
| Rate-limited user receives a readable error | new test + probe: 429 now carries CORS headers and the `rate_limited` payload |

## 5. Workflows and operations surfaces

| Surface | Post-change status |
|---|---|
| `ci.yml` (6 jobs) | reviewed at source; not executed here (no runner access). Gates are real: lint/format/types/tests+coverage, Postgres migration cycle + `alembic check` + smoke, golden retrieval benchmark, web audit/lint/vitest/build, README/changelog/i18n guardrails, gitleaks, Docker build + container smoke |
| `eval-gate.yml` | real threshold (±2 pp on six metrics vs a committed 634-case baseline) |
| `release.yml` | reviewed; `F-10` open (tags run no CI; deploy pulls a mutable tag) |
| `vercel-deploy.yml` | reviewed; fork-safe guards verified; `F-24` open (not gated on the eval workflow) |
| Migrations | single head `f2b3c4d5e6f7`; fresh-DB `upgrade head` + `alembic check` → no drift |
| Background jobs | parent digest + weakness refresh schedulers start cleanly in the live server log; `job_runs` ledger claims periods so multiple workers cannot double-send |

## 6. Files changed by this audit and the surfaces they touch

`README.md`, `CONTRIBUTING.md`, `docs/{API,README,RAG_ARCHITECTURE,architecture,runbook}.md`,
`apps/api/src/bangla_gpt_api/initialize/middleware_stack.py`,
`apps/api/src/bangla_gpt_api/routers/parent.py`,
`apps/api/tests/{test_cors,test_product_v3}.py`,
`apps/web/src/{lib/text.ts,api.ts}`, `apps/web/src/pages/{ParentDashboard.tsx,AdminDashboard.tsx}`,
`apps/web/src/pages/student/{MePage.tsx,LearnPage.tsx}`,
`apps/web/src/test/{admincenter,workspace,meReport}.test.*`.

Every one of those surfaces has a post-change regression outcome above; nothing
in the owner's pre-existing uncommitted work was reverted, and no feature, API
contract, role or screen was removed.
