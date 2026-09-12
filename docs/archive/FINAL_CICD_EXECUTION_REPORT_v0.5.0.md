# Final CI/CD Execution Report — Release v0.5.0

**Date:** 2026-09-08 · **Executor:** ZCode (autonomous, per owner instruction) · **Repo:** github.com/tanviruchahs2580/Bangla-GPT-APP
**Verdict: RELEASE EXECUTED — all local gates green, GitHub CI green (first run caught BUG-4; fixed, re-green), images published to GHCR. Deploy-to-host correctly skipped (owner-gated).**

---

## 1. Executive summary

The accumulated S5/S6 working tree (compliance/k-anon tooling, question-paper pipeline, S6.8 game-day tooling, PWA assets) was brought **live**, tested **end-to-end as a real user in a browser across all five roles**, hardened with **4 real bugs fixed** — two found by live testing (tutor-stream duplicate bubble, unauthenticated data export), one by the local Docker gate (wheel shipped without the KG JSON + PDF font), one by **GitHub CI's Postgres engine check** (account deletion violated FKs that SQLite never enforces) — version-synced to **0.5.0**, gated through the **full local CI matrix**, committed in **9 logical commits**, pushed to `main` (**GitHub CI 6/6 jobs green** + Eval gate + Repository Sanity, with the eval gate active for the first time), and tagged **v0.5.0** — which published `api` and `web` images to GHCR. The SSH deploy job was skipped because `DEPLOY_ENABLED`/SSH secrets are not configured (expected; owner-gated). The owner's no-commit directive was explicitly lifted for this release train.

## 2. Environment & sync verification

| Check | Result |
|---|---|
| Working directory | `C:\Users\DST\projects\Bangla GPT APP` (Git repo, branch `main`) |
| Remote | `https://github.com/tanviruchahs2580/Bangla-GPT-APP.git` (gh CLI auth OK) |
| Baseline | `40f2ff9` = `origin/main` (v0.4.0 release train tail) |
| Stale processes | Old uvicorn/Vite killed; :8000 restarted fresh on the current tree |
| Live sync proof | `/health` → `{"status":"ok","version":"0.5.0","env":"development"}`; :4174 vite preview serves freshly built `dist` |
| Version sync | `pyproject.toml`, `config.py`, `apps/web/package.json`, `README.md` all → **0.5.0** (commit `18b95fb`) |

## 3. Live user-level E2E test (real browser, product flows, all roles)

Executed in the in-app browser against the live stack (API :8000, preview :4174). Highlights — full narrative in `PROGRESS.md` Phase H row:

| # | Flow (as a user) | Result |
|---|---|---|
| 1 | Search hit → chapter reader; theme dark↔light + bn↔en persistence | PASS |
| 2 | AI Tutor question → streamed answer | PASS (final answer rendered twice → **fixed, BUG-1**) |
| 3 | Quiz start → answer → grade; student home progress 20%→30% with correct average | PASS |
| 4 | Revision mini-quiz 5Q → 40% + explain deep-link | PASS |
| 5 | Me page: invite code (1440-min TTL), **data export**, dark/low-data switches | PASS (export 401 → **fixed, BUG-2**) |
| 6 | Parent register → redeem invite → per-chapter accuracy + weak flags | PASS |
| 7 | Teacher: CSV roster import (created ×2 + duplicate-email path) → per-student quiz assign → attempt graded → QPaper draft→review→finalize → paper + answer PDFs valid `%PDF` (11654/12316 B) | PASS |
| 8 | Admin: stats (134 users), safety refusals (insufficient_evidence 116 / sexual_content 4 / self_harm 4), feedback triage, audit `qp_finalize` row, k-anon govt export (min_cell=5, suppressed_cells=2, pii_checked=true), impersonation start→student-scoped→exit→token revoked | PASS |
| 9 | Logout + delete-account UI (redirect + 401 on relogin); QA accounts cleaned via product flows → users back to 129 baseline; retention-purge button never clicked (standing directive) | PASS |

Investigation note: parent dashboard briefly showed an unrelated child — traced to an orphan `parent_student_links` row from a prior session's raw-SQL deletion + SQLite rowid reuse; stale row removed (not a product flow bug — but the same audit surfaced BUG-4 in the product's own delete path, below).

## 4. Bugs found → fixed & regression-tested

| ID | Found by | Defect | Fix + regression |
|---|---|---|---|
| BUG-1 | Live E2E | Tutor stream rendered the final answer as a **second bubble** (stream placeholder id 0 never matched the finalized `message_id`) | Finalize merges the trailing bubble; `tutorStreamDedup.test.tsx` |
| BUG-2 | Live E2E | Me-page data export was an unauthenticated `<a href>` → 401 (auth is header-based) | Authed fetch + blob download; `dataExport.test.tsx` ×2 |
| BUG-3 | Local Docker gate | **Release-blocking packaging bug invisible to pytest** (imports from `src/`): wheel shipped only `data/sample_nctb/*.md`, so the ENV=ci container crashed at boot `FileNotFoundError data/kg/prerequisites.json` (PDF font would ship missing too) | `pyproject` package-data += `data/kg/*.json`, `data/fonts/*.ttf`; rebuilt image: `/health` ok + `/ready provider:mock`, both files verified in site-packages |
| BUG-4 | **GitHub CI (Postgres engine check)** | `DELETE /users/me` violated `daily_activity_student_id_fkey` on Postgres — deletion never covered the S1.9+ child tables (12 student FKs, `class_teacher`, teacher artifacts, 14 user-id refs). SQLite silently ignores FKs, so 489 local tests couldn't catch it | `delete_me` made FK-complete: children deleted; shared history **anonymised, not destroyed** (`audit_log.actor_user_id`, `chapter_content.created_by`, `school_invite.used_by`, redeemed `parent_invite.used_by_parent_id` → NULL); `AuditLog` docstring records the single erasure exception; new `tests/test_delete_cascade_v2.py` ×3 |

## 5. Local CI gates (mirror of ci.yml + runbook SOP) — green

| Gate | Result |
|---|---|
| `ruff check` / `ruff format --check` | PASS (6 files formatted first — unpushed S5/S6 code had never seen the CI-enforced formatter) |
| `mypy src` | PASS (76 files) |
| `pytest -q` | **492 passed, 6 skipped**, exit 0 (pre-BUG-4: 489+6; +3 = new FK-cascade tests). R6 note (honest): the 3 pre-existing extra skips are `REDIS_URL` skipif gates in `test_cache_v2.py` (never run in CI either — no redis service); **proven green against a throwaway real Redis 7: 19/19 passed**, container removed |
| Postgres engine (throwaway `postgres:16` container + `TEST_DATABASE_URL`) | PASS (re-run after BUG-4 fix, container removed) |
| Alembic cycle (throwaway SQLite) up→down→up | PASS → head `a1b2c3d4e5f6` (append-only maintained) |
| `pip-audit` / `npm audit --omit=dev` | 0 / 0 vulnerabilities |
| `vitest run` (apps/web) | 92/92 passed (+3 new this phase) |
| Web `tsc && vite build` | PASS |
| Golden retrieval eval | 15 items, hit@3 = 1.0, grounded 0.9333 |
| Docker build + container smoke (`ENV=ci`) | PASS after BUG-3 fix: `/health` 0.5.0 + `/ready {"provider":"mock"}` |
| Concurrency drill (`scripts/concurrency_probe.py`, throwaway DB copy, port 8030, `LLM_PROVIDER=mock`) | 1c: 0 % err p95 18 ms; 10c under the 30/min/user tutor cap: 0 % err p95 153 ms (~65 RPS). The 65–70 % error bursts at 5–10c/40-req were the rate limiter shedding 429s **by design** (cross-checked vs `rate_limit_tutor_per_minute=30`). dev.db and real Gemini quota untouched; server killed + probe DB deleted afterwards |

## 6. GitHub CI (push `main`)

Push 1 (`40f2ff9..7f78234`): Eval gate **34201358814 success** (first-ever activation of the S4.7 golden-set gate) · Repository Sanity **34201358815 success** · API CI **34201358862 FAILURE** — Postgres engine check only → BUG-4 (all other 5 jobs incl. Docker smoke green).

Push 2 — fix `8f55051` + docs `56b2078`:
- **API CI 34204241960 — success**, all 6 jobs: Lint & test (3.11) ✓ · (3.12) ✓ · Postgres engine check ✓ · Golden retrieval ✓ · Web build & test ✓ · Docker build & container smoke ✓
- Eval gate **34204241973 success** · Repository Sanity **34204241946 success**

## 7. Commits (9 logical commits on `main`)

```
b9ef7a5 fix(web): tutor stream renders one bubble (BUG-1)
93b961d fix(web): Me-page data export via authed fetch (BUG-2)
01f6410 fix(api): ship kg JSON + PDF font in the wheel (BUG-3)
91d461a style: apply ruff format to the CI-enforced baseline
18b95fb chore(release): v0.5.0 — version sync + README status
4c60566 chore(repo): track manifest PWA icons; ignore Capacitor scaffolds and scratch font dir
7f78234 docs(progress): Phase H v0.5.0 finalization entry; honest gate headers
8f55051 fix(api): FK-complete account deletion (DELETE /users/me) (BUG-4)
56b2078 docs(progress): BUG-4 narrative in Phase H entry and evidence log
```

(Commits were staged on `upgrade/master-roadmap` and fast-forward-merged into `main`, keeping both branches identical; `main` pushed `40f2ff9..56b2078`.)

## 8. Release: tag v0.5.0 → GHCR

- Annotated tag `v0.5.0` pushed at `56b2078` (the fully CI-green commit).
- Release & Deploy run **34204637724**: *Build & push images to GHCR* = **success**; *Deploy to production host (SSH)* = **skipped** (`vars.DEPLOY_ENABLED != 'true'` / SSH secrets absent — owner-gated, as designed with health-gated rollback available when configured).
- Images published (workflow-log verified, with digests):
  - `ghcr.io/tanviruchahs2580/bangla-gpt-app/api:v0.5.0` (+ `latest`) — `sha256:4f63c4554d242484182ae28680ed7d5b3aecb86b9387a740da607e04e76e18af`
  - `ghcr.io/tanviruchahs2580/bangla-gpt-app/web:v0.5.0` (+ `latest`) — `sha256:7fc2709a65f3ccf5091274a3ab878fc2f9044bb75a546879276b8b4c6ea87799`
- Note: GHCR packages are **private by default**; owner can flip visibility in Package settings if public pulls are wanted.

## 9. Version sync

| File | Before | After |
|---|---|---|
| `apps/api/pyproject.toml` | 0.4.0 | **0.5.0** |
| `apps/api/src/.../config.py` (`/health`) | 0.4.0 | **0.5.0** |
| `apps/web/package.json` | 0.4.0 | **0.5.0** |
| `README.md` status | v0.4.0 | **v0.5.0** |

## 10. Owner-gated items (unchanged, per repo SOP) & limitations

- **Deploy to a host**: set `vars.DEPLOY_ENABLED=true` + `DEPLOY_HOST/USER/SSH_KEY` secrets; the workflow auto-deploys with health-gate rollback.
- **Real Gemini**: live functional paths exercised; answer quality with the owner-supplied paid key remains to be validated (load drills deliberately used the mock provider to avoid burning quota).
- **G6 staging legs + S6.7 sign-off + S6.1 (NCTB PDFs + permission)**: human steps per standing rule R8 — neither performed nor faked.
- NCTB rights, domain/DNS/TLS (Caddy), SMTP, offsite backup, human UAT — per `docs/LAUNCH_READINESS_CHECKLIST.md`.
- Redis-gated cache tests and the Postgres engine check have no local service by default; both were proven green against throwaway containers this phase (and the Postgres one runs in CI on every push).
- Live-run artifacts (live_test/probe DBs, logs, evidence screenshots) are local-only and git-ignored; `golden_report.json` stays gitignored (regenerable).
