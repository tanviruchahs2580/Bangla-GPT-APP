# Bangla GPT — project instructions

Read `~/.zcode/AGENTS.md` first. It carries the portfolio-wide rules (evidence discipline, approval
boundaries, secret handling, migration safety, ratchets, project isolation). This file adds only what is
true **for Bangla GPT**; where the two conflict, this file wins inside this repository.

**This is a children's product.** Children's educational records and guardian contact data are in scope.
Treat every data-handling decision accordingly, and treat the privacy rules in §6 as non-negotiable.

---

## 1. What this is

An NCTB-textbook-grounded AI tutor for Bangladeshi students (classes 1–12), in Bangla, as a web app, a
PWA, and a Capacitor Android app on Google Play. A two-language monorepo — **there is no root package
manifest**; the two apps are independent.

| Layer | Path | Stack |
|---|---|---|
| API | `apps/api` | Python **FastAPI** ≥ 0.115, SQLAlchemy 2 **sync**, Alembic, pyjwt, argon2-cffi, arq + redis |
| Web | `apps/web` | React 18, Vite 5, react-router-dom 7, TanStack React Query 5, **plain CSS** (no Tailwind), Capacitor 7 |
| Corpus | `data/nctb/` | 9 NCTB PDFs → 852 chunks (content gitignored, provenance committed) |
| Eval | `apps/api/eval/` | Golden sets v2/v3, redteam set, regression baselines |

## 2. Runtime — pin it, do not inherit it

- **Node 24** (`.nvmrc` = `24`, `engines.node` = `>=24 <25`, `engines.npm` = `>=11`).
- **Python ≥ 3.11** (CI runs 3.11 and 3.12; mypy targets 3.11). Installed here: **3.12.10**.
- Package managers: **npm** (`apps/web/package-lock.json`); Python deps pinned by
  `apps/api/constraints.txt` (192 KB, hash-pinned) and verified by `apps/api/scripts/check_lockfile.py` —
  **never hand-edit that file**.
- The sibling project pins Node **22**. Never assume a runtime from another project.

## 3. Ports and process isolation

- Web dev server: **`5173`**, now with `strictPort: true` so a conflict fails loudly instead of silently
  drifting to 5174 — a drift that would surface as a baffling CORS/login failure, because `ALLOWED_ORIGINS`
  and the e2e harness both assume this exact port.
- The e2e harness deliberately uses a **different port per mode**: dev `5173`, preview `5174`, both
  overridable via `E2E_WEB_PORT`, and `e2e/00-identity.spec.ts` asserts the served app really is this
  product. **Do not collapse those ports** — the separation is what stops an audit from sweeping a foreign
  app (see the comment at `playwright.config.ts` around the `WEB_PORT` definition).
- **`5173` is also AgroBridge's dev port.** The two projects' dev servers must not run simultaneously. Run
  one at a time, or override explicitly: `npm run dev -- --port 5273` (plus `E2E_WEB_PORT=5273` for e2e).
  If you override, `ALLOWED_ORIGINS` in `.env*` must match or login fails on CORS.
- API: `API_HOST_PORT` (production template uses `8000`), bound to `127.0.0.1` by default.
- Compose declares `name: bangla-gpt-app` — keep it. (AgroBridge pins `agrobridgeapp`; the names are distinct.)

## 4. Architecture boundaries — enforced by import-linter

Five contracts in `.importlinter`, run in CI via `lint-imports`:

1. `db-is-a-leaf` — the DB layer imports nothing above it.
2. `retrieval-does-not-reach-up` — retrieval must not import services.
3. `providers-do-not-reach-up` — providers must not import services.
4. `nctb-below-services` — the NCTB/corpus layer sits below services.
5. `evaluation-is-offline-tooling` — evaluation code is not part of the serving path.

`curriculum/` is a **PEP-420 namespace package** (no `__init__.py`) — that is deliberate.

**Routers are `apps/api/src/bangla_gpt_api/routers/<domain>.py`** — the
directory holds 19 Python files (18 modules including `__init__.py`): 12
domain routers registered in `routers/__init__.py`'s `_ROUTER_TAGS`, plus
`deps.py` and the underscore-prefixed internal helpers. (CI-FIX-007: the old
"19 of them" counted files, not registered routers.) Count them with
`grep -c "^\s*(" apps/api/src/bangla_gpt_api/routers/__init__.py`'s
`_ROUTER_TAGS` tuple. Use the existing
dependency aliases from `routers/deps.py` — `TeacherOrAdminUser`, `ParentUser`, `AdminUser`,
`SchoolStaffUser`, `require_roles(...)`, `require_ai_budget(...)`, and the tenancy helpers
(`_tenant_school_id`, `_student_in_school`, `authorize_student_access`). Do not hand-roll authorization.

Web: there is **no Tailwind** — styling is plain CSS. State is **TanStack React Query** + an `AuthProvider`
context. Do not introduce a CSS framework or a second state library. TypeScript `strict` with
`noUnusedLocals` and `noUnusedParameters`.

## 5. Bangla text handling — get this right or the feature is silently broken

- **`\w+` is wrong for Bangla.** It splits on combining marks (vowel signs U+09BE–U+09CC, virama U+09CD) and
  destroys words like বিশ্বকাপ. Use the Bangla-block-aware tokenizer
  (`retrieval/hybrid.py::tokenize`, `r"[A-Za-z0-9\u0980-\u09FF]+"`).
- Normalise with NFKC + zero-width stripping (`retrieval/normalize.py`) before safety screening, retrieval,
  or comparison. Preserve the offset map — it drives source highlighting.
- **Romanised "Banglish" input is a first-class path**, not an edge case. Students type `kosh ki`,
  `bhitore ki thake`. Transliteration + bounded fuzzy matching live in `retrieval/transliteration.py`.
  Before this existed, *every* Banglish question abstained.
- **Legacy Bijoy/SutonnyMJ input** must be detected and converted (`nctb/bijoy.py`).
- **`ruff` ignores `RUF001-003` deliberately** — Bengali legitimately uses "ambiguous" codepoints. Do not
  remove those ignores. `scripts/bn_scan.py` is the correct Bangla hygiene check instead.
- Bangla PDF rendering needs `fpdf2` + `uharfbuzz` for correct conjunct shaping, with the bundled fonts
  (`src/bangla_gpt_api/data/fonts/`, OFL-licensed). Do not substitute a font or drop the shaping step.

## 6. Student data protection — non-negotiable

- **Passwords:** Argon2id, OWASP parameters. Never bcrypt, never SHA.
- **PII at rest:** Fernet field-level encryption via `security.py::encrypt_pii_strict`, keyed by
  `PII_ENC_KEY`. It **refuses** to store PII when no key is configured — that refusal is the control, not a
  bug. `Parent.phone_enc` is encrypted this way. Never store a guardian phone in plaintext, never log it,
  never export it.
- **Single-use tokens** are stored as SHA-256 hashes only (`password_resets.token_hash`,
  `email_verifications.token_hash`, `parent_invites.code_hash`). Never store a token in clear.
- **Consent** is versioned: `CONSENT_VERSION = "2026-09-v2"` with re-confirmation semantics, recorded with
  `consent_ip`, `consent_at`, `consent_version`. A consent change means a version bump and a migration path
  for existing students — never a silent edit.
- **The audit log is append-only.** The five privileged event types (`role_change`, `data_export`, `purge`,
  `qp_finalize`, `impersonation`) are never updated or deleted; the single documented exception is account
  erasure, which anonymises the actor id to NULL. `detail` carries only ids and outcome metadata —
  **never message content, never PII**.
- **Retention windows are design decisions, not placeholders.** `answer_log` 730 days, `ai_usage` 365,
  `ai_jobs` 30, token grace 30. `answer_log` exists so "a child's academic record needs an age". Do not
  shorten a window or widen a purge without an explicit instruction.
- **Export and erasure** go through `services/gdpr.py` (`build_data_export`, `erase_account_everything`).
  A new table holding student data must be added to export **and** erasure **and** the retention sweep —
  `test_export_completeness.py` guards this.
- **PII must not reach a third-party model.** `services/pii.py` redacts phone, email and national-ID
  patterns before egress, metered per kind. Never bypass it.
- **Production refuses to boot on misconfiguration** (`main.py::enforce_production_safety`): JWT, CORS, DB,
  PII, metrics, rate-limit/redis, LLM provider, corpus, and AI budget are all validated. `LLM_DATA_USE_TIER`
  must be acknowledged. Never weaken or skip a boot guard to make a deploy start.

## 7. RAG and evaluation — never trade honesty for a nicer answer

- **The grounding gate:** IDF-weighted coverage ≥ 0.5 **and** fewer than 2 absent content terms, else the
  system refuses with `INSUFFICIENT_EVIDENCE_ANSWER` and `grounded=false`. **A refusal is a correct
  outcome.** Never lower a threshold, widen `top_k` (3 for context assembly), relax the term-absence
  budget, or add a fallback that fabricates content in order to turn a refusal into an answer.
- **Vector-only candidates must share Bangla bigrams with the query.** Cosine similarity on the local
  hashing embedder is never standalone evidence — collisions are real.
- **Prompt identity is recorded on every answer.** `PROMPT_VERSION = "tutor-prompt-v1"` and
  `PROMPT_SHA256`. A prompt change **must** bump both.
- **Retrieved evidence, the user question, and attached images are untrusted data**, injected inside
  `<evidence>` / `<attached_image>` delimiters with escaping (`sanitize_evidence`). Keep the
  injection-hardened system prompt and its rule that evidence is reference data, never instructions.
- **The evaluation gate blocks on a > 2 pp regression** vs `apps/api/eval/baseline_v3.json`
  (`evaluation/cli.py`, `HIT_GATE_K = 3`; a 5 pp drop means retrieval broke). Golden sets, a 24-question
  blocking gate, and a redteam set also run in CI. **Never regenerate a baseline to make a change pass** —
  that is a separate, reviewed act.
- **Embedder identity is enforced.** `_verify_embedder_identity()` refuses to serve a corpus whose manifest
  was built with a different embedder or dimension. Changing the embedder is a manifest-breaking event.
- **Safety screening runs before retrieval** (`services/safety.py`): self-harm, weapon/drug synthesis,
  sexual content, violence, personal data, hate speech, bullying — in Bangla, Banglish and English, with
  age-appropriate Bangla refusals. Helpline numbers are pinned to the government-published values
  (১৬২৬৩ / ৯৯৯) and enforced by `test_qa_helpline_policy.py`. Do not edit those numbers.

## 8. NCTB corpus

`data/nctb/{raw,extracted,normalized}/` is **gitignored — the textbooks are copyrighted.** Only provenance
(`manifests/`) is committed. Never commit corpus content.

Chunking is structure-aware (`TARGET_TOKENS = 220`, `MIN_TOKENS = 60`, `MAX_TOKENS = 450`, no overlap;
boundaries follow chapter/section headings; each chunk carries `SourceSpan` offsets). A chunking change
regenerates `corpus_manifest.json` and must pass `apps/api/scripts/check_corpus_manifest.py` and
`apps/api/scripts/content_qa.py` (wired into CI in CI-FIX-001).

There is **no normalised curriculum table** — content is `chapter_contents` (versioned JSON: `summary`,
`notes`, `key_points`, `examples`, `practice_qs`, `homework`, `exam_tips`), plus `concepts` /
`concept_prerequisites` and `practice_items` / `question_bank`.

## 9. Educational evaluation

Elo adaptive difficulty: `DEFAULT_ELO = 1200`, `SIGMA = 200`; the next item targets
`ability + 0.5 * SIGMA` — slightly above current level. Mastery is per concept via `concept_mastery`;
`score_pct = round(100 * correct / total, 2)`.

Never change scoring, difficulty selection, or mastery math without running the golden set — and never
change it to make a specific result look better.

Assessed answers are graded against the **stored rubric**, not a model's impression of quality, and
partial credit is awarded wherever the rubric allows — never collapse a graded answer to pass/fail.
Feedback to a student must be explainable from the rubric. Never invent marks, weights or rubric criteria
that are not in the stored rubric, and never adjust scoring to make a particular result look better.

## 10. Database

Alembic migrations in `apps/api/alembic/versions/` — **36 files counted on
2026-11-10** (`ls apps/api/alembic/versions/*.py | wc -l`). The previous
claim here said 36 too, but the tree held 35 for most of that day: this number
moves with every migration, so re-count it rather than quoting it. Engine
selected by URL scheme in
`db/session.py`: SQLite locally (`sqlite:///./bangla_gpt.db`), PostgreSQL in production (psycopg3). The app
is **SQLAlchemy 2 sync**, not async — do not introduce async sessions.

`db/models.py` holds **42 tables** (`grep -c '__tablename__'
apps/api/src/bangla_gpt_api/db/models.py`; the claims of 46 and of a
"41-table schema" elsewhere in this file were both wrong — CI-FIX-007). Read
the invariant comments. The users role `CHECK` is real now
(`a3c5e7f9b1d3` created it; an earlier claim here that it was
comment-only was stale — the migration-chain audit on 2026-11-12 found
`ck_users_role` in the ORM and both migrations). Remaining comment-only
invariants are vocabulary tables (quiz status, content sources, audit
action) — flagged for a future schema-hardening migration. Never edit an
applied migration — add a new one, per `~/.zcode/skills/safe-db-migration`.

## 11. Generated and serialized artifacts — one writer each

| Artifact | Generated by | Owner |
|---|---|---|
| `data/nctb/manifests/corpus_manifest.json` | corpus build | **AI Engineer only** |
| `apps/api/eval/baseline_v3.json` | eval harness | **AI Engineer only**, never in the same PR as a retrieval change it would mask |
| `apps/api/scripts/check_coverage_floors.py` (`FLOORS`) | ratchet | **QA Engineer only** |
| `apps/web/vite.config.ts` coverage thresholds | ratchet | **QA Engineer only** |
| `CHANGELOG.md` (checked by `check_changelog.py`) | every change | **Principal Architect only** |
| Images/tags, release metadata | release process | **DevOps Engineer only** |

**Ratchets — raise only, never lower:** `fail_under = 80` with per-module floors (e.g. `services/pii.py`
100, `retrieval/hybrid.py` 100, `retrieval/bm25.py` 100, `services/safety.py` 98, `services/gdpr.py` 98,
`services/tutor.py` 91); web `lines 68 / functions 60 / branches 60 / statements 70`. The web config
comment says *"Raise these as coverage grows; never lower or skip them."*

## 12. Gates — exact commands

Every line below runs **from the repository root** (paths are written
root-relative so `check_doc_paths.py` can verify them; the `cd apps/api` is
part of the command where the API tools need it).

```bash
# API
cd apps/api && python -m pytest -q            # 252 test files on 2026-11-12 (`find tests -name 'test_*.py' | wc -l`); pytest-randomly runs by default; pyproject pins asyncio_default_fixture_loop_scope after the pytest bump broke CI
cd apps/api && ruff check . && ruff format --check .
cd apps/api && mypy src                      # CI-FIX-007: bare `mypy` does not run at all ("Missing target module, package, files, or command"); CI and pre-commit both use `mypy src`
lint-imports                                 # the five import-linter contracts (repo-root config)
# Coverage floors: the JSON report is generated, never tracked (CI-FIX-009),
# so produce it first. CI runs the same coverage flags on both matrix legs.
cd apps/api && python -m pytest -q --cov=bangla_gpt_api --cov-branch --cov-report=json
cd apps/api && python scripts/check_coverage_floors.py coverage.json
python apps/api/scripts/check_lockfile.py
python apps/api/scripts/check_changelog.py
# Corpus gates (CI-FIX-001): the tracked-artifact legs always run; the
# served-corpus leg and the content_qa loop need the gitignored corpus and
# skip with a notice when it is absent.
python apps/api/scripts/check_corpus_manifest.py --data-dir data/nctb   # add --corpus-dir data/nctb when the corpus is present
for f in data/nctb/normalized/nctb-*.chunks.jsonl; do python apps/api/scripts/content_qa.py report "$f" || break; done
# or, from the repo root, the skip-aware Makefile target:  make corpus-check

# Evaluation (blocking)
cd apps/api && python -m bangla_gpt_api.evaluation.cli   # exit 1 on > 2pp regression; golden v3 (427 items) vs eval/baseline_v3.json
cd apps/api && python scripts/evaluate_golden.py         # 24-question gate, fails under 0.9

# Web
cd apps/web && npm run lint                  # eslint src --max-warnings 0
cd apps/web && npm run test && npm run test:coverage   # both go through scripts/check_vitest_ran.mjs, so an incomplete vitest run cannot exit 0 (CI-FIX-002)
cd apps/web && npm run deadcode              # knip
cd apps/web && npm run build && npx playwright test
```

`.pre-commit-config.yaml` runs: file hygiene, `detect-private-key`, ruff + ruff-format,
conventional-pre-commit, plus local hooks `gitleaks-history`, `mypy-api`, `eslint-web`, `prettier-web`.

CI adds: pip-audit, semgrep, hadolint, Trivy (image scan in the `docker` job,
npm-lock scan in `guardrails`, release image scan), Postgres smoke, gitleaks
full history, CodeQL, OpenSSF Scorecard, Lighthouse CI, Playwright across
three engines, `eval-gate`, `retrieval-eval`.

**Two corrections to this list, both measured 2026-11-10 (CI-FIX-006):** the
old text claimed `markdownlint` and denied Trivy. Trivy does run (see below);
`markdownlint` does **not** — `.markdownlint-cli2.jsonc` exists and is kept
current, but no job invokes it, and running it with that config on this tree
reported 19 findings in 4 files, so it must not be wired in as a blocking gate
until those are fixed (see §15 "Known gaps"). This project has **no
commitlint** (AgroBridge has both Trivy and commitlint).

## 13. Android and PWA

- **PWA is real**: `apps/web/public/sw.js` + `manifest.webmanifest` + `offline.html`, `index.html` has
  `<html lang="bn">`. Update logic in `src/lib/serviceWorkerUpdate.ts`.
- **Capacitor 7**, `appId app.banglagpt.tutor`, native project at `apps/web/android/` (gitignored scope).
  Release procedure: `docs/mobile_release.md`, `docs/playstore/`.
- **`VITE_API_BASE` must be an absolute URL in release builds.** The Capacitor WebView origin is
  `capacitor://localhost`, so a relative `/api` base cannot reach the backend. This is documented in
  `capacitor.config.ts`; do not "simplify" it.
- **Builds are CI-only.** This machine has no `java`, `gradle`, or `adb`. AAB/APK builds happen in
  `android-release.yml`. `.apk-latest/` holds local copies and is gitignored.

## 14. Approval boundaries specific to this project

Ask before: pushing; running `release.yml`, `vercel-deploy.yml`, or `android-release.yml`; touching
`.env.production*` or any secret; `git filter-repo` or force-push (**the git history contains a removed
1.3 MB `dev.db.bak-wave2` database dump — see below**); running a migration against any non-disposable
database; changing `constraints.txt`; regenerating an eval baseline; changing a retention window, consent
version, or the audit-log policy; editing pinned helpline numbers.

## 15. Known gaps (do not treat as working)

- **A 1.3 MB database blob is in git history — verified synthetic, no action needed.**
  `apps/api/dev.db.bak-wave2` was committed in `5bfbae8` and removed in `320ed1f`; it is reachable from 35
  remote branches and 14 tags. Contents were inspected read-only and are **entirely seed data** from this
  repo's own harnesses (`gate_g3_local.py` → 82 `@g3.test` accounts, plus `example.com`/`live.test`/
  `test.dev`): every email is on a reserved test domain, all 33 `consent_ip` rows share one loopback IP, and
  the 376 chat messages span only 11 conversations. **No real user, child, guardian contact or credential is
  exposed, and no rotation is needed.** Do not propose a history rewrite for this — it would touch 35
  branches and 14 tags for 1.3 MB of test data. Recurrence is already prevented by the `*.db*` `.gitignore`
  rules. **Do not re-escalate this on the strength of the `.gitignore` comment alone.**
- **No DPIA.** `docs/data_minimization.md`, `docs/dpa_template.md`, `docs/security/threat-model.md`,
  `docs/ai/risk-register.md`, `docs/ai/system-card.md` exist — none is a DPIA. This is the governance gap
  for a children's-data product.
- **No embedding model is configured by default.** `embedding_model` defaults to `""`, so the shipped lane
  is the deterministic local `HashingEmbedder` (384-dim). Choosing a real model + dimension is an operator
  decision and a manifest-breaking event.
- **`*.db` files are everywhere in the working tree.** 216 of them (measured
  2026-11-10: `find . -name '*.db' -not -path './.git/*' -not -path
  './node_modules/*' | wc -l`), of which 130 sit under `.audit/`,
  `.qa-work/` and `.audit-work/`; some carry the full 42-table schema
  (`db/models.py`; the old "41-table" and "~14 files" claims here were both
  wrong, CI-FIX-007). Row contents were never enumerated — treat any retained
  one as a PII artifact. They are now ignored by `.gitignore` (CI-FIX-008),
  not only by each clone's `.git/info/exclude`, and excluded from the Docker
  build context (CI-FIX-005).
- **`markdownlint` is declared in CI in this file and wired nowhere.**
  `.markdownlint-cli2.jsonc` exists and is current, but no workflow,
  pre-commit hook or Makefile target invokes it. Measured 2026-11-10 with the
  repo's own config (`npx markdownlint-cli2@0.24.0`): 19 findings in 4 files
  (`docs/adr/ADRs.md` MD025 on each ADR's H1 — the file's deliberate
  multi-document shape — plus MD033/MD031/MD032/MD036/MD038/MD040 in
  `docs/native-review/ui-strings.md` and the two 2026-11-10 QA reports).
  Wiring it as a blocking gate before those are fixed would red
  `guardrails`, and fixing findings inside another stream's in-flight QA
  reports is their change, not this one. The claim in §12 is corrected until
  the follow-up lands (CI-FIX-006).
- **Rollback is documented, but the live path is unexercised.**
  `docs/runbook.md` §7.1 documents the real procedure for the live topology
  (a hand-run `api-live` container — the previous container is kept stopped
  as `api-live-preauditv2`) and §7.3 states plainly that the live API runs
  **SQLite** (`DATABASE_URL=sqlite:////data/app.db`) while
  `docs/backup_dr.md` describes Postgres + pgBackRest. The rollback command
  has not been exercised end-to-end, and there is no `psql`/`sqlite3` client
  on this machine to rehearse the data side (CI-FIX-011).

---

## 16. Frontend engineering studio (added 2026-11-11 — developer-environment setup, not a product change)

A local ZCode setup for frontend work lives **outside** this repository at the
local marketplace directory `Bangla-GPT-Frontend-Studio` (plugin
`bangla-gpt-frontend-studio` v0.1.0: skills `bangla-gpt-design-system`,
`bengali-quality`, `capacitor-mobile-ux`, plus imported `frontend-design`; and
six `/frontend-*` commands). It adds process, not behavior — every rule above
still wins over anything in the studio skills.

**Workflow for frontend tasks:** read-only audit (`/frontend-audit`) → spec
(`/frontend-design-spec`) → plan (`/frontend-plan`) → **user-approved**
implementation (`/frontend-implement`, refuses to start without an approved
plan) → independent review (`bangla-gpt-frontend-visual-reviewer` agent, read-only) →
`/frontend-visual-qa` → `/frontend-release-check` before hand-off.

**Design standards (summary; the plugin skills carry the detail):**

- Inspect first: tokens in `apps/web/src/styles.css` (`:root` and the
  `[data-theme="dark"]` overrides), primitives in `apps/web/src/components/ui.tsx`.
  Reuse before adding — a duplicated component is a defect.
- Semantic tokens over raw values; §4 stands (no Tailwind/shadcn/other
  framework); motion stays within the existing token timings and honors
  `prefers-reduced-motion`.
- Every visible control is functional; no fake metrics or fabricated data;
  loading/empty/error/offline/streaming/permission states are designed, not
  discovered by users.
- Light/dark theme parity and bn/en parity are acceptance criteria. The
  axe sweep variants (light/dark × bn/en) are the minimum automated bar.
- Meaningful visual changes ship with labeled before/after screenshots
  (route × viewport × theme × language). Current-state captures are
  `CURRENT-STATE BASELINE`, never approved design targets.

**Bengali-first UI standards:** all user-facing strings go through
`i18n.ts` `t()` including the numeral policy; Bengali line-height
(`--lh-body`) and glyph shaping are preserved; no `letter-spacing` or
`text-transform` on Bengali text; accessible names, errors, and live
announcements are meaningful in the active language. §5 still governs any
text processing.

**Mobile:** §13 stands — no local Android builds on this machine; mobile UX
verification uses the Playwright `mobile-chromium` project; browser viewport
emulation is never reported as native verification.
