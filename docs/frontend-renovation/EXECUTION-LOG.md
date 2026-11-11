# Execution Log — Bangla GPT frontend renovation

Chronological record of what was run, what it returned, and what was decided. Times are local
(UTC+6). Every entry corresponds to a command whose output is quoted or referenced.

---

## 2026-11-11 · Wave 0 — discovery

| # | Action | Result |
|---|---|---|
| 1 | `git status --short --branch`, `git remote -v`, `git rev-parse HEAD` | Branch `main` tracking `origin/main`; remote `tanviruchahs2580/Bangla-GPT-APP`; HEAD `03dfe21`. **Worktree clean** — no staged, unstaged or untracked files, so there was no owner work to preserve |
| 2 | `node --version`, `npm --version`, `git --version` | `v24.19.0`, `11.17.0`, `2.55.0.windows.5` — matches `.nvmrc` 24 and `engines` |
| 3 | Listed every source file under `apps/web/src` | 41,580 lines across TS/TSX/CSS; ~150 unit-test files; 24 e2e specs; 22 page modules |
| 4 | Read `App.tsx` in full | 25 declared route entries, 5 roles, one `RequireAuth` guard with a 6-step decision order |
| 5 | Delegated: design-system audit (`frontend-design-lead`), capability inventory (`Explore`), harness investigation (`Explore`) | Three read-only reports returned; all load-bearing claims re-verified later (§"Verification of delegated findings" in `TOOLING-INVENTORY.md`) |
| 6 | Discovered `docs/uiux_renovation_evidence/` (46 files) and `docs/route_baseline.md` (144 API routes) | Pre-existing evidence, **not** claimed as evidence for this renovation |

### Decision: scope is repair-and-solidify, not restyle

The audit established the frontend already has 99 semantic tokens, zero loose hex colour, a
real z-scale, Bengali typography guards, contrast guards, six roving-tabindex widgets, a 44 px
tap floor and a print stylesheet. **"Replace a bad design" would have been dishonest.** The
direction became: close the guard blind spots first, fix what they reveal, remove feedback
that lies, and subtract decoration that carries no information — recorded in
`DESIGN-DIRECTION.md` §3 with the rejected alternatives and why.

## 2026-11-11 · Wave 0 — baseline gates (before any product edit)

```
cd apps/web
npm run format:check   →  EXIT 0
npm run lint           →  EXIT 0   (eslint src --max-warnings 0)
npm run test           →  EXIT 0   Test Files 113 passed (113)   Tests 479 passed (479)
npm run build          →  EXIT 0   built in 12.63s
npm run deadcode       →  EXIT 0   (knip)
```

Log: `evidence/test-results/baseline-gates.log`. **No baseline failure existed** in the web
gate set.

Two baseline facts captured from that run and used later:

- The app-entry chunk was **112,989 B gzip against a 125,000 B ceiling** — 90.4 % of budget.
  This constrained every subsequent decision: no dependency, no entry-graph addition.
- The build emitted exactly one warning: `Unexpected "*" [css-syntax-error]` at
  `.stat-*/.table-wrap`. Non-fatal, therefore shipped.

## 2026-11-11 · Baseline defect investigation (R-08)

| Step | Action | Result |
|---|---|---|
| 1 | `grep -n "stat-\*/" src/styles.css` | Line 3060 `.stat-*/.table-wrap` |
| 2 | Read lines 3040-3075 | Found the cause: a comment at 3054 contained `the .btn-*/` — the `*/` closed the comment early, so everything after it became live CSS and `.page-title` was absorbed into a garbage selector list |
| 3 | Inspected the built CSS | Confirmed the emitted selector was one invalid list: `.stat-*/.table-wrap names above. ------ */ .page-title{…}` |
| 4 | Wrote a minimal repro and served it over local HTTP | Loaded in a **real browser**; `rulesFound.probe = 0` — the browser never parses a rule for `.page-title`. `#probe` fell back to the UA `h1`; the valid control selector applied |
| 5 | **Then checked what actually styles an `h1`** | `styles.css:380` already sets `font-size: var(--fs-2xl)` for every `h1`. So the real delta is the bottom margin only: `0.4em` (≈10.9 px at `--fs-2xl`) instead of `--space-4` (16 px) |

**Decision: severity corrected from P1 to P3.** My initial hypothesis — "seven staff
dashboards render unstyled headings" — was wrong, and the measurement is what corrected it.
Recorded as P3 in `RISK-REGISTER.md` R-08 and as a newly-visible margin inconsistency in
`CONTENT-AND-TERMINOLOGY.md` §5.4.

## 2026-11-11 · Independent measurement of the contrast failures (R-02, R-05)

Rather than trust the audit's arithmetic, wrote a reproducible script that reads the real
token values out of `styles.css`:

```
.venv/Scripts/python.exe docs/frontend-renovation/evidence/accessibility/contrast_audit.py
```

Output at baseline:

```
parsed 110 light tokens, 46 dark overrides

F1  hero prompt placeholder (need >= 4.5:1 text)
      over #052e16 = 4.24     over #166534 = 4.31     over #14532d = 4.28
F2  progress-ring track (need >= 3:1 non-text)
      light 1.21     dark 1.16
F3  (ten semantic pairs, all passing, all previously unguarded)
RESULT: FAIL   →  EXIT 1
```

**`parsed 110 light tokens, 46 dark overrides` is itself the R-01 evidence**: the guards saw
99 / 40. The script parses all four blocks; the guards parsed one pair.

## 2026-11-11 · Wave 1 — foundation and P1 repairs

| Slice | Edit | Verification |
|---|---|---|
| 1.1 | New `src/test/cssTokens.ts`; both guards rewired to it | `npx vitest run` on 3 guard files + 2 dependent suites → **64 passed**. `contrastTokens.test.ts` 12 → 27 tests |
| 1.2 | `--hero-placeholder` `#6b7a66` → `#525c4d` | **Negative-tested**: temporarily restored the old value, ran the guard, got `AssertionError: #6b7a66 on the hero fill over --brand-ink: expected 4.242178727885688 to be greater than or equal to 4.5`. Restored, passed |
| 1.3 | `--placeholder` role + global `::placeholder { color; opacity: 1 }` | Asserted on 4 surfaces × 2 themes; browser-verified later |
| 1.4 | `.ring` track → `var(--line-strong)` | Computed candidates first: 70 %/80 % of `--line-strong` give 2.27/2.62 — **both still fail**; 100 % gives 3.54/3.46. Chose the token itself rather than a mix |
| 1.5 | Reduced-motion block: `animation-delay`, `transition-delay`, `animation-iteration-count` | Re-ran `tutorAutoScroll`, `skipLink`, `w2_i18n_css_typography` → pass |
| 1.6 | Comment reflowed; `.page-title` restored | `npm run build` → CSS warning count **1 → 0** |
| 1.7 | `--glass-bg` dark override removed; `voice-pulse` → `voice-blink` | grep confirmed no test referenced either name |

Two of my own mistakes were caught by the guards I had just written:
1. Asserting `hasOwnProperty(DARK, "hero-placeholder")` is false — trivially true because
   `DARK` is the merged map. Corrected to assert the dark layer did not *move* the value.
2. `lastRule("::placeholder")` matched `.hero .home-prompt .input::placeholder`, because the
   shorter selector is a suffix of the longer one. Fixed by adding an exact-selector
   `rulesForSelector()`.

Both are worth recording: a guard that is written but never observed failing is not evidence,
and these two only surfaced because the guard was actually executed.

## 2026-11-11 · Wave 2 — trust repairs

| Slice | Edit | Verification |
|---|---|---|
| 2.1 | `SchoolsCard` loader tracks `invitesFailed`; the invite table renders `LoadError` + retry | Test first failed with **"Found multiple elements with the role alert"** (my query was unscoped — the page has other alerts), fixed by scoping to the invite table via `within()`. Then **negative-tested**: reverted the fix, got `Unable to find role="alert"`. Restored → **6/6 pass** |
| 2.2 | `OfflineLibrary` failure → localized toast; new `offlineDeleteFailed` key in both dictionaries | 2 new tests: failure raises the message and the row remains; success raises none → **4/4 pass**. Added toast-region cleanup to `beforeEach` so one test's message cannot leak into the next |
| 2.3 | `qpAcceptOne` key; per-question button relabelled | **This entry originally read "`qpapers.test.tsx` re-run → pass". That was false.** The rename broke `qpapers.test.tsx:183`, whose selector still used the old label and therefore silently re-pointed at the bulk button. I ran the file but piped the output through `grep`/`head` and read test names instead of the summary line, so the failure scrolled past and I reported a result I had not confirmed. An independent reviewer caught it (`REGRESSION-AND-INDEPENDENT-REVIEW.md` **IR-01**). Repaired: selector updated to `qpAcceptOne`, plus a new test asserting the bulk button still posts all three decisions. `qpapers.test.tsx` → **5 passed** |
| 2.4 | `LoginPage` resend: `<a href="/forgot">` → `Button` | New test asserts `role=button`, `type="button"`, no `role=link`, and that the handler still calls `resendVerification("a@b.com")` → **4/4 pass** |

One edit briefly corrupted `login.test.tsx` (an over-broad `old_string` removed a line); it was
detected on the next read and repaired before any test ran against it.

## 2026-11-11 · Wave 3 — deferred, with reasons

Deliberately not attempted: collapsing the two button vocabularies, unifying the three stat
layouts, and subtracting the decorative layer. Reasons recorded in `IMPLEMENTATION-PLAN.md`
Wave 3 — chiefly that `formControlBoundary.test.ts:107` asserts `button.secondary` as a live
selector, so retiring it means rewriting an accessibility guard in the same change; and that
the decorative subtraction would invalidate nearly all 60 visual baselines at once, which
needs the full review cycle this delivery did not have budget to complete honestly.

**The honest alternative to a half-verified restyle was to not do it and say so.**

## 2026-11-11 · Environment work for browser verification

| Step | Action | Result |
|---|---|---|
| 1 | `netstat` | An API was **already** listening on `:8000` (PID 11048). Not restarted, not reconfigured |
| 2 | `GET /health`, `/live`, `/status` | All healthy and clearly this project's API — so it was identified before anything touched it |
| 3 | Checked DB state read-only | `apps/api/dev.db` 24 users / 0 e2e; repo-root `bangla_gpt.db` 0 users |
| 4 | `make seed` | **FAILED**: the Makefile target resolves `../apps/web/e2e/seed_e2e_users.py` from `apps/api`, i.e. `apps/apps/web/...`, which does not exist. Recorded as **R-19**; **not** fixed (build tooling, outside this frontend scope) |
| 5 | Ran the seed directly with the corrected path | Succeeded: `DATABASE_URL=sqlite:///./dev.db`; `dev.db` then held 31 users including all seven `@e2e.test` accounts |
| 6 | Started the dev server | `npm run dev` → `http://localhost:5173`; `/` 200 and `/api/health` 200. Port 5173 was free (the sibling project's server was not running) |
| 7 | Playwright MCP navigate + evaluate on `/login` | Confirmed **R-04**: a rule-less input resolves `color: rgb(93, 107, 87)` (`--placeholder`) at `opacity: 1`; exactly two `::placeholder` rules are parsed. Confirmed **R-08**: `.page-title { font-size: var(--fs-2xl); font-weight: 700; margin: 0 0 var(--space-4) }` now parses |
| 8 | Screenshot `/login` at 1440 in Bangla/light | `evidence/final/01-login-bn-light-1440.png` — read back and visually inspected. The page renders correctly; its inputs use labels rather than placeholders (which is why `getComputedStyle(el, '::placeholder')` legitimately returns the element colour there) |
| 9 | Attempted an authenticated session without putting the fixture password on a command line | `browser_run_code_unsafe` with `await import('node:fs')` fails with `ERR_VM_DYNAMIC_IMPORT_CALLBACK_MISSING` |

**Decision (step 9): stop hand-driving authenticated pages and use the project's own
Playwright harness instead.** It holds the credential in `e2e/a11y.ts`, it is the tool the
project uses for this, and it yields authoritative pass/fail rather than ad-hoc navigation.
The fixture password never appeared in a command line or a transcript.

## 2026-11-11 · First e2e run — FAILED, and the diagnosis

```
cd apps/web && npx playwright test --project=chromium visual smoke
→ x 1 smoke.spec.ts:66  a student signs in … (25.0s)
→ x 2 smoke.spec.ts:86  a guardian-consented student registers … (34.3s)
```

Failure text: `Expected pattern: not /\/login$/` plus `alert: Email or password is incorrect.`
for `student1@e2e.test`.

Diagnosis from evidence, not guesswork:

1. The spec uses `student1@e2e.test` (`smoke.spec.ts:21`).
2. My seed **did** work — a direct read showed `apps/api/dev.db` holds all seven `@e2e.test`
   accounts.
3. Therefore the running API is **not** serving `apps/api/dev.db`.
4. Cause: `playwright.config.ts` sets `reuseExistingServer: !process.env.CI`, so outside CI the
   harness adopted the already-running API on `:8000` and **skipped its own seeding**, along
   with the test-only `JWT_SECRET` and rate-limit overrides it sets for its own server.

**This is environment targeting, not a product regression.** Neither failing test touched any
code changed by this renovation — smoke test 1 is sign-in + logout, test 2 is registration.
Two defensive checks confirm that reading rather than asserting it: the baseline recorded the
same harness with a clean 217/0/14 junit, and the failures are credential errors rather than
assertion mismatches on anything changed here.

## 2026-11-11 · Isolated e2e run (authoritative)

```
cd apps/web && CI=1 E2E_API_PORT=8100 E2E_WEB_PORT=5273 npx playwright test --project=chromium smoke visual
```

`CI=1` forces `reuseExistingServer: false`; the non-default ports start a **self-contained**
API (which seeds its own throwaway temp SQLite, having `DIRECT_API=true`) and its own Vite dev
server. The owner's services on `:8000` / `:5173` were left running and untouched.

Result so far: **41 of 68 passed, 0 failed**, covering all 8 smoke journeys and 33 of the 60
visual baselines (welcome, login, student-home across light/dark × bn/en × 360/768/1280).
Recorded in `VISUAL-QA-REPORT.md`.

## Standing decisions

- **No commit, push, merge, tag, release, deploy, or container swap was performed.** The work
  is uncommitted working-tree state plus new files.
- **No destructive command was run**: no `reset --hard`, `clean -fd`, forced checkout, branch
  switch, or history rewrite.
- **The owner's running dev API was never restarted or reconfigured.**
- Android/native verification is blocked on this machine and is not claimed.
- The final verdict is `PARTIALLY COMPLETED — BLOCKERS REMAIN`, quantified in
  `FINAL-DELIVERY-REPORT.md`.

## 2026-11-11 · Independent review → repairs → final gate run

Two read-only reviewers (a `security-reviewer` and a `frontend-visual-reviewer` tasked with
*falsifying* the preservation claim) returned 11 findings. Three were defects **I had
introduced**, and one of those I had also mis-reported as passing (`IR-01`). All are fixed:

| Finding | Repair | Verified |
|---|---|---|
| IR-01 rename broke `qpapers.test.tsx`, which silently re-pointed at the bulk button | selector → `qpAcceptOne`; added a guard keeping single and bulk accept separately addressable | 5/5 pass |
| IR-02 `LoginPage.tsx` 361 lines vs a 353 ceiling | handler extracted, comment tightened, fragment dropped → **350 lines**, ratchet untouched | `pageSizeRatchet` + `login.test` pass |
| IR-03 two unused exports turned knip red | removed | knip exit 0 |
| IR-04 reviewed badge still read "Accept all" | new `qpReviewed` key | `qpapers` 5/5 |
| IR-05 inaccurate comment I wrote | corrected to name the tokens that really live only in the later pair | — |
| IR-06 latent cascade trap in the helper | `tokenNamesByBlock()` + disjointness guard | passing |
| IR-07 the motion fix had no test of its own | new `reducedMotion.test.ts` (6 tests) | 6/6 |
| IR-09 full-suite runs were incomplete under concurrent load | all competing processes stopped; one clean run | see below |

Two further defects my own tooling caught before the final run: the new motion test used
unnecessary type assertions (eslint `--max-warnings 0`, exit 1), and my contrast-audit script
had (a) a CWD-relative path that crashed when run from `apps/web`, (b) a hardcoded
`color-mix(--line 70%)` formula so it kept measuring the *old* ring track after the fix, and
(c) a dark map not merged with light, so `--placeholder` raised `KeyError`. All three fixed;
the script now resolves its own path, reads the declarations the stylesheet actually emits,
and exits 0.

### Final gate run (clean, uncontended) — all green

```
cd apps/web
npm run format:check   →  EXIT 0
npm run lint           →  EXIT 0
npx tsc --noEmit       →  EXIT 0
npm run test           →  EXIT 0   Test Files 114 passed (114)
npm run build          →  EXIT 0   built in 16.77s; app entry 113,109 B gzip / 125,000 B
npm run deadcode       →  EXIT 0
contrast_audit.py      →  EXIT 0   RESULT: PASS
playwright smoke visual →  EXIT 0   68 passed (5.4m)
```

Log: `evidence/test-results/final-gates.log`. Baseline comparison: 113 → 114 test files,
bundle +120 B (+0.1 %), CSS minify warnings 1 → 0, contrast audit exit 1 → 0.

### Housekeeping

The dev server started for browser verification was **stopped** (port 5173 released, because
`AGENTS.md` §3 records that AgroBridge uses the same port). The owner's API on `:8000` was left
running and untouched. Final change set: 12 modified files, 2 new test files, 1 new docs tree —
516 insertions, 140 deletions. Nothing committed, pushed, merged, tagged, released or deployed.
