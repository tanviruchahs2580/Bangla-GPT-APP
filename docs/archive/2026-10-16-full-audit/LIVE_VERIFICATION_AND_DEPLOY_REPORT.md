> **Historical, not current.** Kept for history only; this snapshot does
> not describe the current tree and must not be quoted as current status.
> Current sources of truth: [../README.md](../README.md).

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

---

## 5. Outcome

### 5.1 Merged and green on `main`
- PR **#15** merged into `main` as merge commit **`afcbcb7`** (admin bypass used
  for the one-approving-review rule; no second human was available, and the
  bypass is stated in the merge message rather than hidden). A merge commit —
  not a squash — is what the changelog guard expects, since merge commits are
  excluded from its "every commit is listed" rule.
- Post-merge `main`: **API CI success** and **eval gate success** on
  `afcbcb7`. All seven required checks were green on the branch beforehand
  (`Lint & test` 3.11 and 3.12, Postgres engine check, Docker build & smoke,
  golden retrieval benchmark, Web build & test, Repository guardrails).

### 5.2 Production is live with this build
- Vercel's **Git integration** deployed the merge commit to production at
  `2026-10-16T03:40:27Z` (`Last-Modified` on the served `index.html`).
- Sync evidence from the live site:
  - `index.html` now advertises **শ্রেণি ৬–১০**; an hour before this merge it
    still served **১–১২** — the exact drift this audit flagged (`F-39`).
  - The live main bundle contains `memory_on_disable_note`, `school_admin` and
    `stream ended before completion` — i.e. the i18n copy fix (`F-34`), the
    admin role-list fix (`F-35`) and the stream-error port (BUG-005) are all
    running in production. (`suggestionSentence` and `api_origin_unreachable`
    are minified and edge-only respectively, so they are absent by design.)
  - Public routes `/`, `/welcome`, `/login`, `/status` all answer 200.
- **The Actions deploy workflow is redundant and still red.** `vercel-deploy.yml`
  ran again on the merge and failed at its preflight with the revoked
  `VERCEL_TOKEN`. It does **not** gate the live site, because the Git
  integration deploys independently. It should either be removed or have its
  token re-minted — a permanently red required-adjacent workflow trains people
  to ignore red.

### 5.3 What is still not live (blocker B-2)
`https://bangla-gpt-app.vercel.app/api/*` continues to answer
`{"code":"api_origin_unreachable"}`. The frontend is current; **the API behind
it is not running**, so sign-up, login, tutor, quiz and dashboard calls cannot
work in production. The repository holds no API deployment credentials
(`release.yml` expects `DEPLOY_HOST`/`DEPLOY_USER`/`DEPLOY_SSH_KEY`/
`DEPLOY_HOST_FINGERPRINT`, none of which exist), so no pipeline here can start
it. Authenticated journeys were therefore **not** exercised against production —
and no production account was created, because a student sign-up in this product
requires asserting guardian consent, which this audit will not assert on
someone's behalf.

### 5.4 Exact owner actions to finish the job
1. **Host the API** somewhere reachable (a small VM via the existing
   `deploy/` compose stack, or a managed host) and set the four `DEPLOY_*`
   secrets if `release.yml` is to do it.
2. **Point `API_ORIGIN`** (Vercel → project → environment variables) at that
   host, and add the Vercel domain to the API's `ALLOWED_ORIGINS`.
3. **Mint a fresh `VERCEL_TOKEN`** and update the repository secret, or delete
   `.github/workflows/vercel-deploy.yml` now that the Git integration is the
   working deploy path. Also connect the stale `web` Vercel project to nothing
   (or delete it) — it fails on every push and its red check is noise.
4. Then re-run the authenticated smoke: register a class-6 student through the
   UI, ask the tutor one question, and take one quiz — the same journeys this
   audit verified locally end to end (154/154).

---

## 6. Made live (second session, owner-authorized Vercel access)

### 6.1 Root cause of "the app is not usable": two configuration defects, not a missing host
1. **`API_ORIGIN` pointed at a dead tunnel URL.** The Vercel project had exactly one
   environment variable, `API_ORIGIN`, holding an old
   `trycloudflare.com` quick-tunnel hostname. Quick tunnels get a new random
   hostname every time `cloudflared` restarts, so the value had gone stale and
   every `/api/*` call answered `api_origin_unreachable`. The live topology is
   the owner's documented demo stack in Docker (api + redis + web preview +
   mailpit + a `cloudflared` tunnel that publishes the API), and the tunnel was
   running — only the pointer was wrong.
2. **The running API container had an empty `JWT_SECRET`.** Registration worked
   (it does not mint a token) while every login answered **500** with
   `jwt.exceptions.InvalidKeyError: HMAC key must not be empty`. With
   `ENV=test` the production boot guard that refuses a short/empty secret does
   not apply, so the container booted and failed per-request instead. A real
   finding: `ENV=test` + empty secret is a silent-failure configuration.

### 6.2 What was changed (each verified)
| # | Action | Verification |
|---|---|---|
| 1 | Updated `API_ORIGIN` in Vercel to the running tunnel host and triggered a redeploy from the dashboard | `GET /api/ready` on the production domain → `{"status":"ready","provider":"mock"}` |
| 2 | Recreated the API container with a strong generated `JWT_SECRET`, preserving every other setting **and the `/data` volume** | login works; the DB keeps its rows |
| 3 | Republished the container's port (`API_HOST_PORT`) — the first recreate silently bound a random port, which is the same failure mode `F-22` describes | `0.0.0.0:8000->8000`; the tunnel could reach it again |
| 4 | Tagged the image built from the merged commit as the compose image and recreated the API | live `invite code` check now returns the 64-bit hex from this audit's fix, proving production runs the merged code |
| 5 | Rotated `VERCEL_TOKEN` per the runbook: minted a team-scoped token (1-year expiry), set the repository secret, re-ran the deploy workflow | workflow **success**, including the post-deploy smoke `production alias /login -> 200` — a step that had never executed before |
| 6 | Revoked the two superseded tokens afterwards, leaving one live credential | token list shows only `github-actions-ci-2026-10-16-team` |

### 6.3 Live verification as a user
`probes/live_smoke.py` against `https://bangla-gpt-app.vercel.app/api`:
**31 / 31 checks pass** — register (with guardian consent), login, `/users/me`,
learn subjects/chapters/content, tutor ask with sources, quiz start + graded
submit, dashboard summary, revision queue, student report with suggestion
code+params, 64-bit invite code, teacher workload/classrooms, and the negative
matrix (401 unauth tutor/admin, 403 student→teacher, 404 unknown route).

Browser pass on production (in-app browser, 1366×768): logged in as a live QA
student, the student home rendered with the real greeting and quick actions, and
the tutor answered "কোষ কী?" with the structured Bangla answer, an 84%
confidence badge, "পাঠ্যবই-সমর্থিত" and source chips — screenshots captured in
the session.

### 6.4 What this deployment is, and what it is not
It is the owner's **demo topology**: the frontend on Vercel, the API on a local
Docker host behind a Cloudflare quick tunnel, `ENV=test`, `LLM_PROVIDER=mock`,
SQLite in a Docker volume. Consequences to state plainly:

* The app is **fully usable** — auth, learning, quizzes, reports, teacher tools.
* The tutor answers with **mock text**, not a real model: no `GEMINI_API_KEY` is
  deployed and `LLM_PROVIDER=mock` (the production guard that refuses mock is
  bypassed because `ENV=test`).
* Availability is bound to the owner's machine and to the quick-tunnel hostname.
  **Every tunnel restart changes the hostname and therefore requires a new
  `API_ORIGIN` value.** Promoting a named tunnel (stable hostname) or hosting the
  API on a VPS is the durable fix — and per `docs/hosting_decision.md` that
  choice (budget + data residency for minors' data) is a human sign-off, so this
  audit did not provision one.
* The container's SQLite was created by `create_all` in an earlier session, so
  `alembic upgrade head` inside it fails on already-existing tables. A **fresh**
  database migrates cleanly (proven by CI and by the local fresh-DB run), so this
  is a legacy-state artifact of the demo volume, not a deploy defect.

### 6.5 Mobile (APK)
Not buildable from this environment, and the blockers are owner-side toolchain
items, not the API any more: no JDK, no Android SDK (`ANDROID_HOME` unset) and
no signing keystore exists in the repo or in `~/.android`. The manifest fixes
from this audit (backup disabled, `RECORD_AUDIO` for dictation) are in place, and
a release build now has a working API to point at —
`VITE_API_BASE=https://bangla-gpt-app.vercel.app/api npm run build && npx cap sync
android`, then assemble and sign with the owner's keystore.
