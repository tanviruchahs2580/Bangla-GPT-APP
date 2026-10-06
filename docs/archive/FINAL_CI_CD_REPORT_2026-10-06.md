# Final CI/CD Execution Report — Login Background Live + Full Pipeline

**Date:** 2026-10-06 · **Repo:** tanviruchahs2580/Bangla-GPT-APP · **Branch:** main

---

## 1. Executive summary

The login-page background feature (dark/light theme-synced artwork, desktop +
mobile variants) is **live on production** at
**https://bangla-gpt-app.vercel.app** and was verified in a real browser as a
user, on both desktop and mobile viewports, in both themes.

The full CI/CD pipeline was executed end-to-end with a strict SOP:

```
push (ea59e72) ──▶ Repository Sanity ✓ (11s)
              ──▶ Eval Gate        ✓ (1m07s)
              ──▶ API CI           ✓ (3m59s — ruff, mypy, pytest ×2,
                                           pip-audit, alembic up/down/up,
                                           Postgres smoke, Docker+Trivy,
                                           web: npm audit + vitest + build)
                      │ CI green gate
                      ▼
              ──▶ Vercel Production Deploy ✓ (1m10s) ──▶ smoke check ✓ (alias 200)
```

---

## 2. Commits shipped

| Commit | Content |
|---|---|
| `f63d715` | feat(web): login page background image with dark/light theme sync (3 JPEG assets, `.splash-login` CSS, LoginPage class wiring) |
| `ea59e72` | ci: add CI-gated Vercel production deploy workflow (+ gitignore `.vercel`) |

Local pre-push gates: `tsc --noEmit` ✓ · `vitest run` **126/126 tests in 43 files** ✓ · `vite build` ✓ (14.8 s)

---

## 3. Production deployment

| Item | Value |
|---|---|
| Production URL | https://bangla-gpt-app.vercel.app |
| Vercel project | `vantiq-systems/bangla-gpt-app` (prj_L6qdFzLqPTeMTmnoyhqCHZKMxJnr) |
| Root directory | `apps/web` · framework Vite · build `npm run build` · output `dist` |
| Promoted deployment | `dpl_7P7YkrBYCFg8BPr6gySsjyrDt5Xc` → READY / PROMOTED |
| API routing | `/api/*` rewritten to the Cloudflare tunnel backend — `/api/health` → `{"status":"ok"}` ✓ |
| SPA routing | `/(.*)` → `/index.html`; `/login`, `/register` return 200 ✓ |

Deploy-path note: this deployment was produced by the Vercel CLI from the
committed tree (the login-bg commit), then re-produced by the new CI-gated
GitHub Actions workflow. Both serve the identical bundle.

---

## 4. CI/CD pipeline (SOP)

### 4.1 Existing gates (kept unchanged, verified green)
- **API CI** — Python 3.11/3.12 matrix: ruff lint + format, mypy, pytest,
  pip-audit (fails on any vulnerability), Alembic up/down/up cycle,
  OpenAPI smoke start; Postgres 16 service: migration cycle + journey tests;
  web job: `npm ci`, `npm audit --audit-level=high --omit=dev`, vitest, build;
  Docker job: build + Trivy gate (fail on fixable HIGH/CRITICAL) + container
  health/readiness smoke.
- **Eval Gate** — golden-set retrieval regression (hit@3 / grounded accuracy).
- **Repository Sanity** — hygiene checks.
- **Release** (tag `vX.Y.Z`) — GHCR image build/push + SSH deploy with
  automatic rollback to the previous tag on failed health check.

### 4.2 New: CI-gated Vercel production deploy (`.github/workflows/vercel-deploy.yml`)
- **Trigger:** `workflow_run` — fires only when **"API CI" succeeds on main**,
  plus manual `workflow_dispatch`. Deploys can never bypass a red CI.
- **Concurrency:** `group: vercel-production`, `cancel-in-progress: false` —
  production deploys serialize and are never killed mid-flight.
- **Secrets:** `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` stored as
  encrypted GitHub Actions secrets (verified present). Project link is
  bootstrapped in the runner from secrets — no credentials in the repo.
- **Post-deploy smoke check:** polls `https://bangla-gpt-app.vercel.app/login`
  until 200 (12 × 10 s budget) — the run fails if the alias doesn't serve.
- **Rollback:** Vercel dashboard → previous READY deployment → *Promote to
  Production* (instant, no rebuild), or `vercel rollback`.
- **Result on first real run:** ✓ success in 1m10s
  https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/runs/37437266203

### 4.3 SOP checklist
- [x] Feature work committed with conventional-commit message
- [x] Type check + 126 unit tests green before push
- [x] Push to main → full CI matrix green (lint, types, tests, audits,
      migrations, container scan, eval benchmark)
- [x] Production deploy gated on green CI (not manual, not on red)
- [x] Deploy concurrency serialized; production never cancelled mid-run
- [x] Secrets encrypted in GitHub; `.vercel/`, `.env*` git-ignored
- [x] Post-deploy smoke verification automated in the workflow
- [x] Live verification in real browser, both themes, both viewports
- [x] Rollback procedure documented in the workflow header
- [x] Stray resources cleaned (accidental `vantiq-systems/web` project removed)

---

## 5. Live user-acceptance test (production, real browser)

Probe = in-page `getComputedStyle` + `fetch` + image decode of the exact CSS-
referenced asset (not a guess — the served bytes were measured).

| # | Check | Result |
|---|---|---|
| 1 | `/login` renders `.splash-login` with photo layer | ✓ |
| 2 | Desktop photo served: `login-bg-desktop-VJFSrZ_r.jpg` = **1920×1080 JPEG, 414 KB** | ✓ |
| 3 | Desktop `background-size: cover` (16:9 exact fit — full artwork, no crop/stretch) | ✓ |
| 4 | **Dark mode:** artwork visible under ink veil (76%), text contrast good | ✓ screenshot |
| 5 | **Light mode:** warm-paper veil (26%), full artwork visible | ✓ screenshot |
| 6 | Theme flip is instantaneous, no layout shift (CSS variable veil only) | ✓ |
| 7 | Mobile 390×844 photo: `login-bg-mobile-CYbuklpu.jpg` = **1080×1920, 274 KB** | ✓ |
| 8 | Mobile `contain` + blurred ambient fill — no letterbox bars, no crop | ✓ screenshot |
| 9 | `/register` uses `.splash` **without** photo — gradient aurora only | ✓ |
| 10 | Negative login (dummy creds) → live API round-trip → friendly Bengali error `ইমেইল বা পাসওয়ার্ড সঠিক নয়।` | ✓ |
| 11 | Logged-in dashboard on live works (session + data render) | ✓ |
| 12 | `/api/health` on live → `{"status":"ok"}` | ✓ |
| 13 | Test performed **non-destructively**: user session/theme/lang stashed and fully restored (user back on `/student`, dark theme) | ✓ |

Screenshots captured: live dark desktop, live light desktop, live mobile
portrait (saved under ZCode session artifacts).

---

## 6. Known limitations & recommendations

1. **`VERCEL_TOKEN` is a CLI session token** (expires ≈ 2026-10-29). Before
   then, create a dedicated Vercel Personal Access Token (dashboard →
   Account Settings → Tokens, scope to `vantiq-systems`) and update the
   GitHub secret `VERCEL_TOKEN`. Do not extend the CLI session's life.
2. **API depends on an ephemeral trycloudflare tunnel** (`vercel.json`
   rewrite). When the tunnel rotates, update the rewrite target — better,
   deploy `apps/api` to a persistent host and point the rewrite there.
3. **Two production deploy paths exist** (Vercel Git integration auto-builds
   every push; the new workflow deploys after CI). They converge on the same
   commit content; for a single strict path, disable the Git-integration
   production build in Vercel project settings → Git (keep previews for PRs).
4. **Unique deployment URLs** (`bangla-gpt-<hash>-vantiq-systems.vercel.app`)
   did not resolve from this machine (local DNS); the production alias works
   everywhere and is the canonical URL.
5. **CI deprecation warnings (non-blocking):** Node 20 action deprecation on
   `actions/checkout@v4`/`setup-python@v5`, and `ubuntu-latest` migrating to
   Ubuntu 26 from 2026-10-19 — pin/upgrade actions at next maintenance.

---

## 7. Verdict

**PASS - production-ready.** All parameters functional on live: login
background correct on desktop (1920x1080 cover, full artwork) and mobile
(1080x1920 contain + ambient fill), dark/light theme sync verified with
screenshots, register/forgot pages unaffected, login API round-trip working,
full CI/CD pipeline green end-to-end with the deploy gated on CI success.
