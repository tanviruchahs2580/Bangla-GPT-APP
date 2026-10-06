# Initial QA & Engineering Audit — Bangla GPT APP

> **Date:** 2026-10-06 · **Version audited:** 0.9.2 (working tree at `ea59e72` + 261 uncommitted files) · **Mode:** Pre-remediation baseline (Phase A–C of the master audit directive). No code has been changed by this audit.

---

## Executive Summary

The Bangla GPT APP is a two-app monorepo — a FastAPI + SQLAlchemy 2 + Alembic backend (`apps/api`, 108 source files) and a React 18 + Vite 5 + TypeScript web client (`apps/web`, 34 pages/components) — implementing an NCTB-aligned Bangla tutor with five roles, school tenancy, hybrid RAG retrieval, child-safety moderation, and an unusually disciplined CI pipeline (5 workflows: lint/mypy/pytest matrix, pip-audit, Postgres journey tests, golden-eval gate, web tests, Docker + Trivy).

**Baseline health is good**: every automated gate passes locally (ruff, ruff format, mypy, 631 pytest tests, `tsc && vite build`, 126 vitest tests). The codebase is not AI slop in structure — it has real error contracts, privacy engineering (hash-stored tokens, Fernet PII encryption, k-anonymised exports), and honest honesty-fields in UX.

However, the audit **confirms four security defects** (one bypassable production gate, one brute-forceable MFA path, one cross-tenant write, one CORS/method defect), a set of tenancy inconsistencies, meaningful dead/duplicated logic in the rate-limit and CORS wiring, a production-availability risk in the web→API deployment topology (ephemeral Cloudflare tunnel), and material documentation drift (README version banner, 111 of 134 live API operations undocumented, an internally-contradictory "100/100" scorecard). None of these are P0; the P1 set is small and fixable with minimal, surgical changes.

---

## System Inventory

| Layer | Technology | Evidence |
|---|---|---|
| API | FastAPI ≥0.115, Pydantic v2 settings, PyJWT, SQLAlchemy 2, Alembic, arq, Redis, Prometheus, Sentry, pypdf/fpdf2, cryptography (Fernet) | `apps/api/pyproject.toml` |
| Auth | PBKDF2-SHA256 (200k), HS256 JWT, TOTP MFA (step-up token), impersonation w/ JTI deny-list | `apps/api/src/bangla_gpt_api/auth/security.py`, `auth/mfa.py` |
| Data | 30+ tables, SQLite dev / Postgres 16 prod, single-line migration chain | `apps/api/src/bangla_gpt_api/db/models.py`, `alembic/versions/` |
| AI | Provider abstraction (gemini/openai/mock), hybrid BM25+hash-vector retrieval with RRF fusion, child-safety moderation, teacher content generators | `providers/`, `retrieval/`, `services/safety.py` |
| Web | React 18, react-router 7, @tanstack/react-query 5, react-markdown + KaTeX, lucide icons, Capacitor 7 (Android), PWA manifest + service worker, self-hosted Bangla fonts | `apps/web/package.json`, `index.html` |
| CI/CD | 5 workflows: API CI (py3.11+3.12, pip-audit, alembic cycle, smoke), Postgres job, golden-eval gate, web (npm audit + vitest + build), Docker (Trivy gate); tag-driven GHCR release; CI-gated Vercel deploy | `.github/workflows/` |
| Deploy | Non-root Docker image w/ healthcheck, docker-compose, Vercel (web) — web→API via Cloudflare tunnel URL baked into `vercel.json` | `Dockerfile`, `docker-compose.yml`, `apps/web/vercel.json` |

**Git state:** `main` at `ea59e72`; 261 files modified uncommitted (mechanical comment-ID cleanup that also broke ~8 comment sentences); two local branches fully merged into main (0 ahead); no secrets tracked (verified via `git ls-files`).

---

## Current Architecture

```
[Student/Teacher/Parent/SchoolAdmin/Admin browsers + Android (Capacitor)]
        │  HTTPS
        ▼
[Vercel: static SPA (apps/web/dist)]  ──/api/* rewrite──▶  [EPHEMERAL trycloudflare tunnel]  ──▶  [Docker: FastAPI API (gunicorn+uvicorn workers)]
                                                                                                          │
                                                                    ┌────────────────────────────────────┤
                                                                    ▼                ▼                   ▼
                                                              SQLite/Postgres   Redis (cache/ratelimit)  Gemini/OpenAI/Mock LLM
                                                                                                          ▲
                                                              Inline schedulers / arq worker (jobs.py) ───┘
```

Trust boundaries: browser↔SPA (public), SPA↔API (JWT bearer), API↔DB/Redis (private), API↔LLM (egress with PII redaction). School tenancy enforced per-query via `school_id` scoping helpers (`routers/deps.py`). Boot guard refuses production start on weak secrets/CORS/PII config (`main.py:61-180`).

---

## Baseline Build/Test Status

| Command (working dir) | Result | Notes |
|---|---|---|
| `git status` / `git branch` | PASS | 261 modified files (WIP comment cleanup), 2 stale merged branches |
| `ruff check .` (apps/api) | PASS | All checks passed |
| `ruff format --check .` (apps/api) | PASS | 219 files formatted |
| `mypy src` (apps/api) | PASS | 0 issues in 108 files |
| `pytest -q` (apps/api) | PASS | **631 passed, 4 skipped** in 9m37s |
| `npm run build` (apps/web) | PASS | tsc clean; main chunk 289.7 kB (96.4 gzip), lazy markdown chunk 392.4 kB (119 gzip) |
| `npx vitest run` (apps/web) | PASS | **43 files, 126 tests** |
| `run_web_tests.ps1` (apps/web) | **FAIL** | Uses `--reporter=basic`, removed in vitest 4 (F-D03) |
| `pip-audit` / `npm audit` | NOT RUN LOCALLY | Gated in CI; not re-executed in this audit |

---

## Critical User Journeys (verified by test-suite mapping, not yet runtime-driven)

1. Student register → login → ask grounded question (SSE) → rate-limited, safety-screened, coverage-gated (`routers/tutor.py`, `services/safety.py`) — covered by 631 pytest incl. exploit tests (`tests/test_phase1_exploits.py`).
2. Teacher: classroom import → assignment → question paper review→finalize→PDF (HIL gate `teacher_content.py:606-632`).
3. Parent: invite-code linking → weekly/monthly report (`routers/parent.py`).
4. School admin: tenancy-scoped overview/students/analytics (`routers/school.py`).
5. Admin: role change (last-admin guard), impersonation w/ audit + revocation, feedback triage, k-anonymised aggregate export.

---

## Findings by Category (summary; details in Security / AI-RAG / UX / Docs sections)

| ID | Sev | Conf | Category | Finding |
|---|---|---|---|---|
| F-01 | P1 | Confirmed | Security | `/metrics` prod auth bypassable with any `Bearer` header |
| F-02 | P1 | Confirmed | Security | No rate limit on `POST /auth/mfa/challenge` (TOTP brute-force) |
| F-03 | P1 | Confirmed | Security | Cross-school guardian-consent write skips tenancy gate |
| F-04 | P1 | Confirmed | Security | School-less teachers see platform-wide student PII; self-serve teacher registration |
| F-05 | P2 | Confirmed | Security | Password change/reset doesn't revoke existing session JTIs |
| F-06 | P2 | Confirmed | Security | CORS missing `PATCH` (breaks cross-origin PATCH) + registered twice |
| F-07 | P2 | Confirmed | Config | `RATE_LIMIT_RULES` setting silently ignored; rules triplicated |
| F-08 | P2 | Confirmed | Security | Impersonation revocation fail-open writes false "stop" audit row |
| F-09 | P2 | Confirmed | Security | `/feedback` accepts arbitrary message/attempt ids (cross-user write) |
| F-10 | P2 | Likely | Security | school_admin with NULL school reads default-school staff roster |
| F-11…F-19 | P3 | Confirmed | Security/Perf | Export-while-forced-reset, body-limit swallow, job error leak to users, unbounded queries (roster/dashboard/assignments), missing `/quizzes` limit, LIKE wildcards, no FK ondelete, missing HSTS |
| F-20…F-27 | P4 | Confirmed | Security | Enumeration timing, raw token logs (dev), PBKDF2 200k, 403/404 oracle, consent asymmetry, roster-import 500 race |
| A-* | — | — | AI/RAG | See §AI/RAG Findings (pending agent completion — placeholder) |
| FE-01 | P2 | Confirmed | DevOps/UX | Production SPA proxies `/api` to an ephemeral `trycloudflare.com` URL |
| FE-02 | P3 | Confirmed | Testing | `run_web_tests.ps1` broken (vitest 4 removed `basic` reporter); no `test` npm script |
| FE-03 | P4 | Confirmed | Deps | `dompurify` declared, never imported (dead dependency) |
| FE-04 | P4 | Confirmed | Security | JWT in localStorage (standard SPA tradeoff; XSS-mitigated by react-markdown no-raw + CSP; acceptable, documented) |
| D-01 | P3 | Confirmed | Docs | `docs/API.md` documents 29 of 134 live ops (111 undocumented) |
| D-02 | P3 | Confirmed | Docs | README banner says v0.7.0; manifests/CI say 0.9.2; CI table missing eval-gate.yml + vercel-deploy.yml rows |
| D-03 | P3 | Confirmed | Docs | `docs/FINAL_ENTERPRISE_100_SCORECARD.md` claims Security 12/12 & 100/100 — contradicted by F-01…F-04 |
| D-04 | P4 | Confirmed | Git | ~8 comment sentences broken by WIP cleanup (dangling `, )`); 2 stale merged branches; root doc sprawl (4 audit reports + 122 KB PROGRESS.md tracked) |

---

## Security Findings

**F-01 — `/metrics` auth bypass (P1, Confirmed).** `routers/system.py:97-108`: the gate reads
`if expected and token != expected and not auth.lower().startswith("bearer "): raise 403`.
Any `Authorization: Bearer <garbage>` short-circuits the check, so the production-mandated token (`main.py:157-166` forces `METRICS_REQUIRE_AUTH` + `METRICS_TOKEN`) does not actually authenticate. Route inventory + per-endpoint latency leak to anonymous scrapers. *Fix:* require `secrets.compare_digest` on either the header token or the bearer credential; add regression test for `Bearer wrong` → 403.

**F-02 — MFA challenge unthrottled (P1, Confirmed).** `routers/auth.py:350-377` verifies a 6-digit TOTP (±1 step ⇒ 3 valid codes) with no rate-limit rule covering `/auth/mfa/challenge` (`config.py:162-170`, `initialize/middleware_stack.py:50-62`). Password+unlimited guesses defeats MFA. *Fix:* add rule `("/auth/mfa/challenge", 5, "ip")` to both rule tables; regression test.

**F-03 — Cross-tenant consent write (P1, Confirmed).** `routers/users.py:293-309`: for `teacher`/`school_admin`, `allowed = True` with no `_assert_student_in_school` — the read sibling (`users.py:261-271`) does gate. A teacher from school A can rewrite consent evidence of school B's student. *Fix:* gate teacher/school_admin through the tenancy helper; keep admin unrestricted; regression test.

**F-04 — School-less teachers = platform-wide visibility (P1, Confirmed, documented legacy).** `routers/deps.py:168-180` + `routers/common.py:378-398`: `school_id=None` disables the tenancy wall; combined with open teacher self-registration (`schemas.py:145-160`) any verified email can read roster names/scores/weak-matrix platform-wide. *Fix (smallest safe):* refuse roster/analytics endpoints with 403 `no_school` for school-less teachers instead of returning platform data.

**F-05..F-10 (P2)** as tabled above; **F-11..F-27 (P3/P4)** include the information-leak in `AiJob.error` (`workspace.py:220-238` persists `str(exc)` while the adjacent comment claims the opposite), missing `ondelete` on all FKs, HSTS absence, and the `except Exception: pass` patterns in `middleware.py:131-143` and `initialize/dependencies.py:81-95`.

---

## AI/RAG Findings

Audit of the retrieval/grounding/provider/eval layer (`retrieval/`, `services/tutor.py`, `services/circuit_breaker.py`, `providers/`, `services/generators/`, `evaluation/`, `nctb/`, `data/`).

| ID | Sev | Conf | Finding |
|---|---|---|---|
| A1 | P1 | Confirmed | Gemini vision sends raw `bytes` inside the JSON payload (`routers/common.py:244` → `providers/gemini.py:125`) — every student image question with `LLM_PROVIDER=gemini` dies as a `TypeError` 500 or an aborted SSE stream. Fixed: re-encode to base64 string after validation. |
| A2 | P1 | Confirmed | Circuit breaker can never recover: (1) fallback-served successes cleared the OPEN breaker's recovery timestamp, pinning traffic to the fallback forever; (2) `check_primary_health()` consumed the HALF_OPEN probe, starving the real call and leaving the breaker stuck HALF_OPEN → permanent 502 with no fallback; (3) a failed HALF_OPEN probe did not re-open. Fixed: non-consuming `peek_allows_request()`, OPEN-state successes ignored, probe failure re-opens, `select_provider` routes back to the primary when healthy. |
| A3 | P2 | Confirmed | Conversation history entered the prompt unsanitized (PII-redaction only) — a prior turn could fake `<evidence>` blocks that the model treats as textbook text with real citations; `</user_question>` was also escapable. Fixed: history passes through `sanitize_evidence`; `<user_question>` delimiters neutralized. |
| A4 | P2 | Confirmed | Mid-stream provider failure concatenated the truncated primary output with the fallback stream. Fixed: chunks reset on fallback activation. |
| A5 | P2 | Confirmed | "Not in the textbook" model replies were recorded as `grounded=True` with sources (system prompt rule ৪ instructs exactly this reply). Fixed: canonical marker detection downgrades to `grounded=False, refused_reason="model_refused"` in both JSON and SSE paths. |
| A6 | P2 | Confirmed | The ingest-time prompt-injection filter (`strip_injections`) ran only on the sample corpus — the production NCTB load path (`data/nctb_loader.py`) bypassed the first documented injection defense. Fixed: filter applied at load time with a drop counter. |
| A7 | P2 | Likely | Safety moderation was Bangla-script-only; romanized-Bangla/English self-harm text (the helpline category) passed with no refusal. Fixed: conservative romanized/English variants added to the self_harm pattern. |
| A8 | P3 | Confirmed | BM25 trigram fallback recomputed 3-gram sets over the whole corpus per query; `_trigrams` field dead. (Deferred — perf refactor, results identical.) |
| A9 | P3 | Confirmed | No `max_output_tokens` on any provider call — looping responses inflate the cost ledger. (Deferred — needs a settings knob + payload wiring.) |
| A10 | P3 | Confirmed | OpenAI provider silently ignores images; the student believes the picture was seen (violates the app's own vision-honesty contract). (Deferred — product decision: refuse vs implement vision.) |
| A11 | P3 | Confirmed | Rate-limit rule `/tutor/chat` matched no real route — the chat LLM endpoint was only IP-limited. Fixed: key renamed to `/tutor/conversations` (30/min per user). |
| A12 | P3 | Confirmed | Fallback successes were recorded as primary-breaker successes, masking primary health and feeding A2-mechanism-1. Fixed: only primary-served calls feed the primary breaker. |
| A13 | P3 | Confirmed | Golden v2 positives are built with the system's own gate (near-tautological); the CI eval gates the BM25 baseline while production serves hybrid retrieval. (Deferred — structural eval work.) |
| A14 | P3 | Likely | Zero-width characters (ZWSP/ZWJ/ZWNJ/BOM) bypassed the safety and injection regexes. Fixed: stripped in `normalize_query` (same set the corpus pipeline strips). |
| A15 | P3 | Confirmed | Circuit-open-no-fallback stream path emitted the outage notice twice. Fixed. |
| A16 | P3 | Confirmed | Connection-level transport errors are never retried (only HTTP statuses). (Deferred.) |
| A17 | P3 | Confirmed | LLM-judge faithfulness extraction could read a mid-sentence "1" as a perfect score. Fixed: tail-anchored extraction. |
| A18 | P3 | Confirmed | `--redteam` runs the suite twice (double cost). (Deferred.) |
| A19 | P4 | Confirmed | `light_stem` docstring contradicted the constant (said 4, actual 3). Fixed. |
| A20–A25 | P4 | — | Chunk-ID collision risk, lesson-plan missing echo gate, grammar_score Latin penalty, RAG cache key omits corpus version, count-based memory truncation, dead `answer is None` branch. (Documented; not fixed in this pass.) |

**What is SOLID (verified):** RRF fusion with deterministic tie-breaks; the conservative coverage gate + chapter-scope fallback before refusing; the vector-lane bigram guard against vector-only candidates; PII redaction metered by kind at egress; pooled provider clients with explicit close, timeouts, capped backoff; rules-first deterministic model routing with the fast lane never serving images; generator validation gates (echo checks, MCQ shape, alignment coverage, difficulty tolerance, duplicate Jaccard) with HIL finalization; hermetic eval design with an explicit "never re-baseline to go green" rule; honest class-level detection that refuses to guess; fingerprint dedupe and Bangla-ratio gates in the corpus pipeline.

---

## UX/UI Findings

- Verified positive: a11y attributes are deliberate (`aria-label` from i18n, `aria-hidden` on decorative icons, `role="status"` banners — `AppShell.tsx:77-240`); `index.html` is Bangla-first (`lang="bn"`, bn_BD og.locale, theme-boot as external file for strict CSP); no `dangerouslySetInnerHTML` anywhere; no marketing-slop copy ("AI-powered/Smart" absent from UI strings).
- FE-01 (P2): the production deployment depends on an ephemeral quick-tunnel for its API (commit history shows repeated manual repoints: `0a4bec2`, `7d04b14`, `45aea3c`). This is an availability/UX defect at the deployment layer, not a UI defect — every tunnel rotation breaks the whole app for end users.
- Bundle: KaTeX+react-markdown lazy chunk is 392 kB (119 gzip) — loaded only with markdown content; acceptable but the largest lever if startup cost matters.

## Accessibility Findings

- Strong baseline semantics (landmarks, labelled icon buttons, i18n'd labels). Formal keyboard-only/contrast audit not yet executed (needs runtime; marked `NEEDS_RUNTIME_VALIDATION` for the final report). axe-core is available in devDependencies but not wired as a gate.

## Performance Findings

- No fabricated metrics. Static observations: Python-side pagination in `school.py:663-723` (roster sliced in memory), whole-table loads in dashboard/parent progress paths (`learn.py:656-689`, `parent.py:405-443`), per-request full-school id set for tenancy checks (`deps.py:183-193`). All are P3 with small SQL-aggregate fixes; several duplicate SQL-aggregate code that already exists in the same tree.

## Testing Gaps

- No test covers the F-01 bearer bypass (existing `tests/test_metrics_auth.py:43-54` only tests `x-metrics-token`).
- No rate-limit test for MFA challenge (F-02); no cross-tenant consent-write test (F-03).
- Web tests never run through the documented script (FE-02); CI covers them, but the local DX path is broken.

## Git Findings

- 261-file uncommitted WIP (comment-ID cleanup) with ~8 mechanically-broken sentences — needs grammar repair, then a single `chore` commit.
- Two stale local branches fully merged into main (`feature/ui-ux-blueprint-upgrade-20260830`, `upgrade/master-roadmap`) — candidates for deletion **with owner approval** (not deleted by this audit).
- No secrets tracked; `.gitignore` correctly covers `.env*`, `*.db`, `*.log`; root logs/DBs are untracked local clutter.

## GitHub Findings

- Verified from workflows only (no GitHub API access in this environment): CI is comprehensive and matches README's table except two unlisted workflows (`eval-gate.yml`, `vercel-deploy.yml`).

## Documentation Findings

- D-01/D-02/D-03 as tabled. The "100/100" scorecard is the highest-credibility-risk artifact: it asserts Security 12/12 while the security section of this audit lists four confirmed P1s. Recommend archiving it behind `docs/archive/` with a superseded banner.
- `.env.example` / `.env.production.example` coverage verified against `config.py` Settings — complete (all fields documented, optional ones commented).

## AI-Slop Risk Findings

- **Overall: LOW–MEDIUM.** Not slop: error contracts, honesty fields, privacy engineering, 631 meaningful tests, disciplined CI. Slop residue: triplicated rate-limit rule tables (one dead), duplicated chat-turn logic (`tutor.py` send vs stream), triplicated chapter-accuracy rollup (`learn.py` ×2, `parent.py`), duplicate CORS registration, dead `build_limiter` merge, dead `dompurify` dep, 7 giant functions >100 lines (`services/tutor.py:272,435` etc.), misleading comments contradicting code (`workspace.py:230-231`, `ratelimit.py:102-104`, `auth/security.py:44-49`).

## Dependency/Infrastructure Findings

- `dompurify` unused (FE-03). `pip-audit`/`npm audit`/Trivy are CI-gated (good); local re-run deferred to remediation validation.

---

## Severity Matrix

| Severity | Count | IDs |
|---|---|---|
| P0 | 0 | — |
| P1 | 4 | F-01, F-02, F-03, F-04 |
| P2 | 7 | F-05…F-10, FE-01 |
| P3 | 14 | F-11…F-19, D-01, D-02, D-03, FE-02, (+AI/RAG pending) |
| P4 | 8 | F-20…F-27 subset, FE-03, FE-04, D-04 |

## Root-Cause Analysis

1. **AuthZ asymmetry** (F-01, F-03, F-04, F-09, F-10): tenancy/ownership gates are applied per-endpoint by hand rather than via a single dependency; each new endpoint can forget one. Root cause: no shared `Depends` gate for "staff of this student's school" and no central metrics-auth dependency.
2. **Config dead-ends** (F-07, F-06): middleware wiring evolved (`main.py` → `middleware_stack.py`) without deleting the old path; settings grew without a consumer.
3. **Docs drift** (D-01..D-03): docs were hand-written at v0.5 and never regenerated; scorecards were aspirational.
4. **Deployment topology** (FE-01): no stable API origin exists; a quick tunnel is the current stand-in.

## Quick Wins (smallest safe changes)

1. F-01 + F-02 + F-06 (≈10 lines total + tests). 2. F-03 (1 line + test). 3. Fix broken WIP comments, commit WIP. 4. README version banner + CI table rows. 5. Fix `run_web_tests.ps1` reporter + add `test` script. 6. Remove `dompurify`. 7. Archive the false scorecard.

## Medium-Term Improvements

Session-revocation epochs (F-05); feedback ownership guard (F-09); school-less-teacher policy decision (F-04 — product decision required); consolidate rate-limit rules to one source of truth (F-07); SQL-aggregate dedup for dashboards; `ondelete` migration; stable API origin for production (custom domain or managed tunnel).

## High-Risk Refactors (do NOT attempt in this pass)

Chat-turn unification (send/stream); auth-dependency unification across all routers; FK `ondelete` backfill across 30+ tables.

## Items That Cannot Yet Be Verified

- AI/RAG deep findings (agent audit in progress — appended before remediation).
- Runtime journeys in a live browser (requires running stack; planned during remediation validation).
- GitHub-side settings (branch protection, secret scanning) — no API access from this environment.
- Vercel/tunnel production behavior (needs environment access).
