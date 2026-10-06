# Bangla GPT — Final Engineering, QA, Security, UX & Repository Certification Report

> **Date:** 2026-10-06 · **Head at certification:** `ecca3ef` · **Certification state: B — READY WITH KNOWN RISKS**
> Companion baseline: `docs/INITIAL_QA_AUDIT_2026-10-06.md` (untracked; all findings F-* backend/security, A-* AI/RAG, FE-* frontend, D-* docs).
>
> **ROUND 2 (same day, owner-directed):** every remaining Known Risk was remediated and the app was
> re-certified by live user-acceptance testing. Head after round 2: `6c2e462` + P4/format commits
> (see §11). New verdict: **A− — READY; one deployment step remains (set `API_ORIGIN` in Vercel).**

---

## 11. Round 2 — Known-Risk Remediation (2026-10-06, local commits, unpushed)

| Risk | Fix | Commit |
|---|---|---|
| F-04 | School-less staff anchored to the shared default school (`BGPT-DEFAULT`) — platform-wide roster/analytics/weak-matrix/per-student reads of real schools are gone; standalone-teacher workflow preserved inside the wall. Test contracts updated deliberately. | `ecfe6e3` |
| F-05 | `users.sessions_invalidated_at` token epoch + `iat` claim: password change/reset revokes every earlier-second token; legacy iat-less tokens fail closed. Additive reversible migration `d7e8f9a0b1c2`. | (auth commit) |
| F-08 | Impersonation revocation fails closed: strict cache ops; a Redis outage now answers 503 `revocation_unavailable` instead of a false 204/stop-audit-row; uncheckable imp tokens are refused. | `7d79d9e` |
| FE-01 | Hardcoded trycloudflare tunnel removed from `vercel.json`; Vercel Edge proxy forwards `/api/*` to `API_ORIGIN` env (503 `api_origin_unconfigured` when unset). **Owner step: set `API_ORIGIN` in Vercel project settings.** | (web commit) |
| A8 | BM25 trigram sets precomputed at build (identical scores, O(n) per-query recompute gone). | `6c2e462` |
| A9 | `LLM_MAX_OUTPUT_TOKENS` (default 2048) wired into OpenAI `max_tokens` / Gemini `maxOutputTokens`. | `fd52eca` |
| A10 | Providers declare `supports_vision`; openai/mock image turns refused with `vision_unsupported` at the route; provider-level raise as backstop. | `fd52eca` |
| A13 | Golden gate retrieves through HybridIndex (production mode); golden set grown to 24 items with content-window paraphrases + new negatives → hit@3 1.0, grounded accuracy 1.0. v2 gate untouched (no re-baselining). | `6c2e462` |
| A16 | Transport-level errors retry under the same backoff; mid-stream drops never replayed. | `fd52eca` |
| A18 | Redteam leak scan reuses `run_suite` responses — single pass. | `6c2e462` |
| A20 | Chunk ids hash full text + chapter sequence (boilerplate-prefix collisions impossible); sample-corpus ids content-hashed. | `6479bfa` |
| A21 | Lesson-plan payloads must echo subject/class_level (same gate as all generators); prompt + mock updated. | `6479bfa` |
| A22 | grammar_score Latin penalty proportional; baseline_v2.json regenerated to the new metric definition (documented, not a green-wash). | `6479bfa` |
| A23 | RAG cache keys carry a corpus fingerprint (no cross-corpus hits on shared Redis). | `6479bfa` |
| A24 | Chat history replay per-message char-capped (`CHAT_HISTORY_MESSAGE_CHAR_LIMIT=2000`). | `6479bfa` |
| A25 | Dead `answer is None` regeneration branch removed. | `6479bfa` |

**Round-2 validation:** full API suite **664 passed / 4 skipped**; web build clean + **vitest 133/133**
(7 new proxy tests); ruff + ruff format + mypy clean (108 files); migration upgrade→downgrade→upgrade
cycle green; golden eval hit@3 1.0 / grounded accuracy 1.0; eval-v2 gate PASS; redteam PASS.

**Round-2 user-acceptance testing (live, GUI):** welcome page (BN render), student register →
dashboard, grounded tutor ask with evidence modal + honesty badges, out-of-domain honest refusal
(0% confidence, no fabricated sources), 5-question quiz → graded feedback, logout → login → resume
state, teacher register → dashboard → classroom create → 8-section lesson-plan generation — all
passed on `http://localhost:5173` against the local API (mock provider), plus repo e2e journey
(21/21) and smoke (7/7). One pre-existing UX nit recorded: the lesson-plan flow shows a generic
error when the teacher has no classroom yet (designed flow: create a class first).

**Remaining after round 2:** set `API_ORIGIN` in Vercel (deployment config, one step); shared
default school remains a sandbox for standalone teachers (documented design); PBKDF2 200k and
API.md partial coverage (D-01) unchanged (P3/P4 backlog).

---

## 1. Executive Summary

A full-stack audit (backend, AI/RAG, frontend, DevOps/docs/repo hygiene) of the Bangla GPT APP v0.9.2 monorepo was performed against the current working tree, followed by surgical remediation of every confirmed P1/P2 defect and the low-risk subset of P3s. All fixes carry regression tests. Final validation: **641 passed / 4 skipped (API pytest), 126 passed (web vitest), ruff lint + format clean, mypy clean, golden-eval gate green (grounded accuracy 0.933)**.

The application is certified **READY WITH KNOWN RISKS**: no P0 defects exist; the four confirmed P1s are fixed or (one case) explicitly gated on a product decision; the remaining risks are documented below with concrete fix paths.

## 2. Scope Audited

- **Backend** (`apps/api`): routers, services, auth/MFA/impersonation, school tenancy, middleware stack, rate limiting, caching, jobs/schedulers, config & production boot guard, db models, GDPR delete/export, audit logging.
- **AI/RAG**: retrieval (BM25/vector/RRF hybrid), grounding & refusal gates, prompt construction & injection defenses, provider layer (gemini/openai/mock) incl. streaming and circuit breaker, teacher generators, evaluation harness, NCTB corpus pipeline.
- **Frontend** (`apps/web`): api client, auth/session handling, routing guards, markdown/KaTeX rendering, a11y semantics, i18n, PWA/Capacitor, build & test setup, vercel.json deploy topology.
- **DevOps/docs/git**: 5 CI workflows, Dockerfile/compose, env docs vs Settings, docs accuracy & sprawl, git history/branches/artifacts, tracked secrets scan.

## 3. What Was Verified (evidence)

- Baseline gates run locally: ruff, ruff format, mypy (108 files), pytest, tsc+vite build, vitest, golden eval.
- Security defects reproduced by code reading (all four P1s independently re-verified before fixing).
- `docs/API.md` vs live OpenAPI diff (29 of 134 operations documented → route_baseline.md now referenced).
- `.env.example`/`.env.production.example` coverage vs `config.py` (complete).
- Git: no secrets tracked; `.gitignore` covers env/db/logs; branch divergence measured.

## 4. What Was Changed (this audit's commits, all local — nothing pushed)

| Fix | Defect | Change |
|---|---|---|
| F-01 | `/metrics` prod auth bypassable with any Bearer header | constant-time token comparison on x-metrics-token OR Bearer; deny if unconfigured (`routers/system.py`) |
| F-02 | `/auth/mfa/challenge` unthrottled (TOTP brute-force) | rate-limit rule (5/min/ip) in both rule tables + parity test |
| F-03 | Cross-school guardian-consent write | teacher/school_admin behind `_assert_student_in_school` (`routers/users.py`) |
| F-06 | CORS missing PATCH + double registration | PATCH allowed; CORS registered once in `middleware_stack` |
| F-07 | `RATE_LIMIT_RULES` silently ignored; rules triplicated | rules effective via `_effective_rules` precedence (per-field knobs win on their 4 routes); dead merge deleted |
| F-09 | `/feedback` accepted arbitrary others' message/attempt ids | ownership verified → 404/403 (`routers/tutor.py`) |
| F-10 | school_admin without school read default-school staff | 404 `no_school` (mirrors sibling endpoint) |
| F-11 | Data export allowed during forced password change | removed from exempt paths |
| F-12 | Body-size middleware swallowed all read errors | narrowed to `(OSError, MemoryError)` + clean 400 |
| F-13 | AiJob persisted raw exception text to users | stores exception type name only |
| F-17 | Admin user-search LIKE wildcards unescaped | escaped with `escape="\\\\"` |
| F-19 | No HSTS in production | added when `is_production` |
| A1 | Gemini vision sent raw bytes in JSON → guaranteed 500 on every image question | base64 string re-encoded after validation |
| A2/A12 | Circuit breaker could never recover (fallback pinning / stuck HALF_OPEN / no probe-failure reopen); fallback successes attributed to primary | non-consuming `peek_allows_request`, OPEN-success guard, HALF_OPEN failure re-opens, primary-served attribution only, explicit route-back-to-primary |
| A3 | Conversation history unsanitized (fake-evidence / `</user_question>` escape) | history through `sanitize_evidence`; user_question delimiters neutralized |
| A4 | Mid-stream fallback concatenated truncated primary output | chunks reset on fallback |
| A5 | "Not in textbook" replies marked grounded=True with citations | marker detection → `grounded=False, refused_reason="model_refused"` |
| A6 | NCTB corpus load path skipped the injection filter | `strip_injections` at load time + drop counter |
| A7 | Romanized/English self-harm text bypassed moderation | conservative romanized patterns added |
| A11 | Chat per-user limit key matched no real route | `/tutor/chat` → `/tutor/conversations` |
| A14 | Zero-width chars bypassed safety/injection regexes | stripped in `normalize_query` |
| A15 | Outage notice emitted twice on stream failure | single emission, grounded downgraded |
| A17 | LLM-judge score could read mid-sentence "1" as 1.0 | tail-anchored extraction |
| A19 | `light_stem` docstring wrong | corrected |
| FE-02 | `run_web_tests.ps1` broken (vitest 4 removed `basic` reporter) | fixed + `npm test` script added |
| FE-03 | `dompurify` declared, never used | removed (bundle 289.7→288.9 kB) |
| D-02/D-03/D-04 | README version drift, false "100/100" scorecard, root doc sprawl | resolved in parallel-owner commits (`82a2245`, `1ef6f56`) — README rewritten, scorecard purged, reports archived to `docs/archive/` |

Test-contract updates (behavior deliberately changed, documented in-test): forced-change sessions get 403 from export (F-11); feedback requires an existing owned target (F-09); breaker recovery now re-tests the primary (A2).

## 5. Validation Actually Run

- `pytest -q` (apps/api): **641 passed, 4 skipped** (full suite, post-fix).
- Targeted: test_audit_remediations (8), test_circuit_breaker (24), test_password_reset, test_product_v3, test_metrics_auth, test_cors, test_eval_v2 — all green.
- `ruff check` + `ruff format --check`: clean. `mypy src`: clean (108 files).
- Web: `npm run build` clean; `npm run test`: **126/126**.
- `scripts/evaluate_golden.py`: hit@3 1.0, grounded accuracy 0.933 — gate green.
- NOT run locally: pip-audit / npm audit / Trivy (CI-gated; unchanged by this work).

## 6. Remaining Risks (evidence-based)

| ID | Sev | Risk | Recommended path |
|---|---|---|---|
| F-04 | P1→decision | School-less teachers (self-registered, no school) read platform-wide rosters/analytics/weak-matrix — pinned by `tests/test_auth_teacher.py` as intended standalone-teacher behavior. NOT changed unilaterally. | Owner decision: require school linkage for roster endpoints, or scope school-less teachers to students they actually teach. |
| FE-01 | P2 | Production SPA proxies `/api/*` to an ephemeral `trycloudflare.com` host (documented in README as top infra TODO). Every tunnel rotation breaks production. | Stable API origin: VM/PaaS + domain or named tunnel. |
| F-05 | P2 | Password change/reset does not revoke existing access-token sessions. | Token epoch (`sessions_invalidated_at` + `iat` check) — needs a migration. |
| F-08 | P2 | Impersonation revoke is fail-open if Redis is down (false "stop" audit row; token lives ≤15 min). | 503 `revocation_unavailable` when cache unreachable before writing the audit row. |
| A8/A9/A13/A16/A18 | P3 | BM25 trigram per-query cost; no `max_output_tokens`; CI eval gates BM25 (not hybrid) with near-tautological positives; transport errors not retried; redteam suite runs twice. | Documented in the initial audit with fix paths. |
| A10 | P3 | OpenAI provider silently ignores images (dishonest vs the vision-honesty contract). | Refuse with `vision_unsupported` (mirror mock) or implement vision. |
| A20–A25 | P4 | Chunk-ID collision risk, lesson-plan echo gate, grammar_score Latin penalty, RAG cache key corpus version, count-based memory truncation, dead regeneration branch. | Batch cleanup. |

## 7. Unverified Areas

- Runtime UX journeys in a live browser (keyboard-only, screen reader, slow network, long conversations) — require a running stack session.
- GitHub-side settings: branch protection, required checks, secret/code scanning, Dependabot state (no API access from this environment).
- Performance measurements: no synthetic numbers were produced; static analysis only.
- Capacitor/Android runtime behavior.

## 8. Git/GitHub State

- All audit fixes are committed locally: `ecca3ef` (this audit's batch) plus owner commits that absorbed earlier fixes (`ac5f668`, `1ef6f56`, `829d642`, `82a2245`, `2eeedf3`, `b534505`, `4a89ba5`, `b85d7e1`).
- **Nothing pushed** — per push policy, push awaits explicit authorization.
- Untracked, owner's call: `docs/INITIAL_QA_AUDIT_2026-10-06.md` (full baseline report; kept local — superseded by the owner's canonical `docs/qa-audit-2026-10-06.md`). Session scratch scripts `scripts/_patch_p1.py` and `scripts/_strip_tags.py` were removed on 2026-10-06 after their changes landed in `ecca3ef`.

## 9. Final Scorecard

| Sector | Score | Basis |
|---|---:|---|
| Frontend | 8/10 | clean architecture, deliberate a11y/i18n, 126 tests; no e2e, markdown chunk 119 kB gzip |
| Backend | 8/10 | tight validation, honest errors, 641 tests; some unbounded queries and duplicated rollups remain |
| Architecture | 8/10 | clear module boundaries, deterministic middleware order; chat-turn send/stream duplication remains |
| Security | 8/10 | all confirmed P1/P2 code defects fixed with tests; F-04 product decision pending; PBKDF2 200k below OWASP 600k guidance |
| AI/RAG | 8/10 | grounding gate + injection defenses + refusal honesty now consistent; eval still gates BM25 not hybrid (A13) |
| UX/UI | 8/10 | no slop patterns found; runtime UX audit not performed |
| Accessibility | 7/10 | strong static semantics; no runtime keyboard/contrast audit or axe gate |
| Performance | 7/10 | no measured regressions; documented O(n) hot paths |
| Testing | 8/10 | behavioral suites + exploit tests + eval gates; golden-set tautology risk (A13) |
| DevOps | 9/10 | 5 real workflows, Trivy/pip-audit/npm-audit gates, Postgres job, CI-gated Vercel, non-root Docker |
| Git | 8/10 | logical commits, no secrets; one parallel-session revert incident, cleanly resolved |
| GitHub | 8/10 | workflows match docs; server-side settings unverified |
| Documentation | 7/10 | now honest and indexed; API.md still partial (29/134 ops; route_baseline covers 139) |
| Maintainability | 8/10 | mypy/ruff clean; a few >100-line functions remain |
| **Overall** | **7.8/10** | Weighted mean; certification B |

## 10. AI-Slop Risk Assessment: LOW

Removed during this pass: dead rate-limit merge with a lying comment, dead `dompurify` dependency, duplicated CORS registration, duplicate outage emission, stale docstrings, exception-body leak contradicting its own comment, a fabricated 100/100 scorecard. Remaining: a few giant functions and one triplicated rollup — ordinary tech debt, not generated boilerplate. The codebase reads as intentionally engineered: error contracts, honesty fields, privacy engineering, and tests that fail when features break.
