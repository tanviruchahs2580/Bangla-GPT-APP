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
  (`apps/web/.vercel/project.json`) is intact: `rootDirectory: apps/web`,
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

| Step | Result |
|---|---|
| Suites before the pipeline | API **828 passed / 6 skipped**; web **165 passed / 48 files**; ruff, mypy, eslint, tsc, vite build, README/changelog/i18n guardrails all green |
| Branch | `audit/2026-10-16-live-verification` (SOP: no direct pushes to `main`) |
| Commits | (1) Android release assets + QA record, (2) verified remediation, (3) this audit package |
| Required checks on `main` | 7 contexts: Lint & test (3.11), Lint & test (3.12), Postgres engine check, Golden retrieval benchmark, Web build & test, Repository guardrails, Docker build & container smoke |
| Branch protection | 1 approving review required, `dismiss_stale_reviews`, `require_last_push_approval`, `strict`; admins can bypass (`enforce_admins: false`) |
| Deploy path | merge to `main` → CI + eval gate → `vercel-deploy.yml` (`workflow_run` on a successful main push) → `vercel --prod` |

Local execution limits (stated, not hidden): Docker's daemon is not running on
this machine, so the Postgres migration cycle and the container smoke test are
**NOT RUN locally** — they run in the GitHub job instead. The golden eval CLI was
likewise left to CI.
