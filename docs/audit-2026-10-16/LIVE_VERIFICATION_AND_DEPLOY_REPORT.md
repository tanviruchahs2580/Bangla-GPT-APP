# LIVE VERIFICATION & DEPLOY REPORT — Bangla GPT APP (2026-10-16, second session)

Session scope: verify every function and parameter as a real user on a running
stack, then execute the CI/CD pipeline and make the app live.

---

## 1. Production diagnosis — why the app is not live

Two independent defects, both confirmed from the outside (no provider
credentials were needed to observe them):

### B-1 · Vercel deploy token is dead (blocks every deploy)
- **Evidence (provider, via GitHub run logs):** run `38740539035`
  ("Vercel Production Deploy", `main`, 2026-10-15T13:11Z) fails in the
  preflight step:
  `Error: The token provided via --token argument is not valid.`
  and the workflow's own message: *"Vercel refused VERCEL_TOKEN. It was revoked
  or expired on the Vercel side; re-saving the same value in GitHub will not fix
  it. Mint a new token and follow docs/runbook.md 'Vercel deployment token'."*
- The same job failed at 11:40Z the same day, so this is persistent, not a blip.
- The repository **does** have `VERCEL_TOKEN`, `VERCEL_ORG_ID` and
  `VERCEL_PROJECT_ID` secrets configured, and the project link
  (the project link kept under `apps/web/.vercel/`) is intact:
  `rootDirectory: apps/web`,
  framework `vite`, build `npm run build`, output `dist`.
- **Not resolvable from here:** the local Vercel CLI is logged out and no token
  exists on disk (only an expired `VERCEL_OIDC_TOKEN`). Minting a replacement
  requires interactive login to the owner's Vercel account.

### B-2 · The deployed frontend cannot reach any API
- **Evidence (runtime):** every `/api/*` request to
  `https://bangla-gpt-app.vercel.app` answers
  `{"code":"api_origin_unreachable","message":"The API origin is configured but
  did not respond. This is an upstream outage, not a client error."}` — that is
  the edge proxy in `apps/web/api/[[...path]].ts` reporting that
  `API_ORIGIN` is set but the host behind it does not answer.
- The repository has **no** deployment credentials for the API
  (`release.yml`'s `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY` /
  `DEPLOY_HOST_FINGERPRINT` secrets are absent — the only secrets in the repo
  are the three Vercel ones). So no pipeline in this repository can currently
  deploy the backend, and `API_ORIGIN` points at something that is down.
- **Consequence:** even a successful frontend deploy would ship an app whose
  login, tutor, quiz and dashboard calls all fail. Making the app *live* needs
  both B-1 and B-2 fixed.

### Live version vs. the repository (sync check)
- The live `index.html` still advertises **"শ্রেণি ১–১২"** in its meta
  description; the working tree changes that to **৬–১০**
  (`apps/web/index.html`, guarded by `landingStats.test.ts`). The live bundle is
  therefore an **older build than the current source**.
- Live asset timestamp: `Last-Modified: Thu, 15 Oct 2026 21:37:45 GMT`.
- Verdict: **live ≠ final version** (see §5 for the post-merge re-check).

---

## 2. Functional verification as a user (before touching the pipeline)

### 2.1 Full-surface API journey — 153 checks, 153 passed
`probes/e2e_full_surface.py` against a live server (isolated DB, mock provider).
Log: `logs/e2e_full_surface.log` (local; `*.log` is gitignored).

Coverage: all five roles end-to-end — student (catalogue → chapter content →
progress → tutor ask → conversation → SSE stream → feedback → events → quiz
start/submit/double-submit → revision → KG gaps → search → dashboard → notes →
notifications → prefs → memory → weekly+monthly report → export → invite code),
teacher (workload → classrooms → CSV roster import → short tests → assignments →
progress → weak matrix → coverage → support plans → question paper draft →
regenerate → shuffle → PDF → lesson plan → worksheet/homework/rubric generation →
documents → background jobs), parent (invite redemption → children → child
report → single-use enforcement), school_admin (join by invite → overview →
students → teachers → classes → coverage → analytics), admin (users + filters →
role change → school create → invites create/list → feedback triage → AI quality →
refusal audit → audit log → system info → aggregate reports → impersonation +
exit → maintenance purge), plus the auth surface (consent gate, duplicate/unknown
credentials, password rotation, MFA enrolment) and ten negative authorization
checks.

Three behaviours that looked like failures during development were **verified as
correct product behaviour**, not bugs:
- a self-registered teacher cannot assign work to a student outside their school
  (`403 other_school`) — tenancy is enforced; the suite now asserts the refusal;
- a support plan is refused with `422 no graded quiz data for this student`
  rather than inventing a plan from nothing;
- the quiz endpoint is POST-only, so `GET /quizzes` returns 405.

### 2.2 Live rejection-path verification (the middleware fix)
Against a second instance with production-like limits (2 logins/min, 2 kB body
cap, a configured CORS origin):

| Probe | Result |
|---|---|
| Preflight `OPTIONS /auth/login` | 200 with `Access-Control-Allow-Origin`, and it does **not** consume the budget (2 real attempts allowed, 3rd → 429) |
| 429 body | `{"detail":{"code":"rate_limited","message":"Rate limit exceeded"}}` **with** `Access-Control-Allow-Origin` |
| 413 oversized body | **with** `Access-Control-Allow-Origin` |
| Foreign origin | 200 with **no** `Access-Control-Allow-Origin` (CORS still enforcing) |

### 2.3 Browser pass as a user (38+13 screenshots, two viewports)
Both previously-fixed defects confirmed on screen:
- missing chapter → **"লোড করা যায়নি" + "আবার চেষ্টা করুন"** (the old "no chapters
  found" text is gone);
- student report sentence → **"পরামর্শ: দুর্বল অধ্যায়গুলোতে বেশি অনুশীলন করুন:
  কোষ।"** — real chapter name, zero `{...}` placeholders anywhere on the page
  (same for the parent's child report);
- admin feedback triage → **rows rendered**, never stuck on "লোড হচ্ছে…".

---

## 3. Defects found by the live pass, and what was done

| ID | Sev | Defect (found by the live pass) | Status |
|---|---|---|---|
| `F-34` | P2 | `GET /students/me/memory` code `memory_on_disable_note` had no dictionary entry, so the student saw the **raw key** as visible text — same class as the `{chapters}` bug | **FIXED** + test |
| `F-35` | P2 | Admin role list omitted `school_admin` (the API accepts it), so a school_admin row **displayed as "student"** and any edit on that row would demote the account | **FIXED** + test |
| `F-36` | P2 | The short-test form silently posted to the **first** classroom regardless of which class the teacher was working in; no picker, and submit looked enabled with no classroom | **FIXED** (picker added, submit disabled without one) + test |
| `F-37` | P3 | The home tile "মিনি কুইজ (৩টি প্রশ্ন)" started a **5**-question quiz | **FIXED** (now honours `?count=3`) |
| `F-38` | P3 | A 30-mark question paper answers with `502 "question paper generation failed"`, which the UI renders as "সার্ভার এখন ব্যস্ত" (server busy). The real cause is the requested size exceeding the generated bank — a client-side constraint reported as an upstream outage | OPEN (finding; error semantics) |

Also confirmed in the browser and already tracked: the `CreatePage` duplicate-key
console warning (`F-28`), destructive admin actions with no confirmation
(purge, invite revoke, document delete), mobile layout clipping on `/admin`
(h1 at x=0) and a teacher sidebar strip wider than the viewport, and an
English-only impersonation banner.

New regression tests are non-vacuous: with the pre-fix code restored, all three
new tests fail (`3 failed | 9 passed`) and pass again after the fix, with the
files restored byte-identically.

---

## 4. Pipeline execution

SOP followed: branch → commits → pull request → required checks → merge →
deploy. Nothing was pushed to `main` directly.

### 4.1 First attempt failed on a stale clone (recorded, not hidden)
The branch was first cut from `bbac954`, the commit the working tree had been
based on. `origin/main` had already advanced to `42ae3f9` (PRs #9, #10, #14),
which the local clone's remote-tracking ref did not show until an explicit
`git fetch`. The PR therefore conflicted, and GitHub never created a
`pull_request`-triggered workflow run — the failure looked like "CI is not
starting" but was a mergeability problem. Lesson recorded for the process:
fetch before declaring a baseline.

### 4.2 Rebase and re-verification
Rather than replay diffs, every carried change was re-checked against
`42ae3f9` and only the still-needed ones were re-applied (disposition table in
`AUDIT_FINDINGS.md` §Addendum). Two carried items had been implemented upstream
by PR #10 and were dropped in favour of upstream's code, keeping only their
regression tests. Two others turned out never to have reached `main` and were
re-applied, each proven necessary by a carried test failing without them
(teacher AI budget: 6 failures; teacher rate-limit rules: 9 failures).

Verification on the rebased tree:

| Gate | Result |
|---|---|
| `pytest -q` (apps/api) | **950 passed, 6 skipped, 1 failed** |
| the one failure | `test_chat_history_crud.py::test_message_search_finds_own_history` — passes in isolation (`6 passed`); a per-process 60s rate-limit window shared by the whole suite makes it speed-dependent (recorded as `F-41`) |
| `vitest run` (apps/web, after a clean `npm ci`) | **183 passed / 49 files** |
| ruff, ruff format, mypy | exit 0 |
| eslint, tsc, vite build, prettier | exit 0 (after the CI-found fix below) |
| Guardrails (README, changelog, i18n) | exit 0 |
| All-roles E2E over real HTTP | **154 / 154 checks pass** |

### 4.3 What CI caught that local runs did not
The first hosted run failed two required checks — both real, both fixed:

1. **Repository guardrails** — `check_changelog.py` requires every commit to be
   represented in `CHANGELOG.md`, and a commit is only exempt if it touches
   that file itself. The branch commits were not. Fixed by regenerating the
   changelog and amending it into the commit that carries it.
2. **Web build & test** — `main` added `npm run format:check` to the web job
   after this branch's baseline, and seven of the files this branch touched
   were unformatted. Fixed with `prettier --write` on exactly those files
   (formatting only; lint, 183 tests and the build still pass).

Hosted results for the remaining checks on the corrected branch: Postgres
engine check **pass**, Docker build & smoke **pass**, golden retrieval benchmark
**pass**, eval gate **pass**, Web build & test **pass**.
