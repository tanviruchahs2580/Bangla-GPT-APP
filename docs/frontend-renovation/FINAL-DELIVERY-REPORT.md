# Final Delivery Report — Bangla GPT frontend renovation

**Date:** 2026-11-11 · **Repository:** `Bangla-GPT-APP` · **Branch:** `main`
**Baseline commit:** `03dfe21b6f90bc27ca476bfa459318a14bf3d266`
**Changes:** uncommitted working-tree state plus new files. **No commit, push, merge, tag,
release, deploy or container swap was performed.**
**Authorised scope:** frontend only. No API, database, model, prompt, RAG, or configuration change.

---

## 1. Verdict

### `PARTIALLY COMPLETED — BLOCKERS REMAIN`

**Why not `COMPLETED — VERIFIED`.** The master prompt's bar requires that *every discovered
applicable feature* has a post-renovation positive-path functional PASS, every accessible route
has a smoke PASS, and Android/device checks are passed or genuinely out of scope. Two of those
conditions are not met:

1. **The per-feature functional matrix was not executed.** ~200 capability rows were
   catalogued from source; roughly 190 of them were not individually driven end to end.
   They are covered by the register, by 114 passing unit/component test files, and by the
   smoke and visual sweeps — which is not the same thing.
2. **Android/WebView verification is impossible on this machine** (`AGENTS.md` §13: no `java`,
   `gradle` or `adb`). The product *is* shipped as a Capacitor Android app, so this is an
   in-scope surface that is blocked rather than not applicable. Browser viewport emulation is
   **not** reported as device testing.

**Why not `NOT COMPLETED`.** Fifteen substantiated defects were fixed with regression guards
that were each demonstrated to fail against the pre-change code. Every static gate is green.
All 68 browser tests pass, including all 60 visual baselines with no re-baselining. No feature
was removed, disabled, orphaned or mocked. Two independent reviewers audited the diff and every
finding they raised is dispositioned.

**National-scale readiness is not claimed.** Frontend evidence cannot establish backend
reliability, traffic capacity, or operational readiness.

## 2. Scope completed and not completed

| Area | Status |
|---|---|
| Repository/environment safety audit, baseline gate capture | **Complete** |
| Feature-lock register, route inventory, role journey matrix | **Complete** — ~200 rows, 25 routes, 5 roles, every row `file:line`-referenced |
| Measured, reproducible contrast audit | **Complete** — `evidence/accessibility/contrast_audit.py`, exit 0 |
| Wave 1 — guard blind spot + P1/P2 accessibility repairs (7 fixes) | **Complete** |
| Wave 2 — honest-feedback and semantics repairs (4 fixes) | **Complete** |
| Independent review, findings dispositioned (11 findings) | **Complete** |
| Full clean gate run + browser verification | **Complete** |
| Wave 3 — primitive consolidation + decorative subtraction | **Deferred, reasoned** |
| Per-feature functional matrix across all ~200 rows | **Not done** |
| Android / WebView / device | **Blocked by environment** |
| Field performance measurement | **Unavailable** — no RUM source |

## 3. Test evidence

All commands run from `apps/web`. Full log: `evidence/test-results/final-gates.log`.

| Check | Exact command | Environment | Result | Exit | Evidence |
|---|---|---|---|---:|---|
| Format | `npm run format:check` | win32, Node 24.19.0, npm 11.17.0 | **PASS** | 0 | `final-gates.log` §1 |
| Lint | `npm run lint` (`eslint src --max-warnings 0`) | same | **PASS** — zero warnings | 0 | §2 |
| Typecheck | `npx tsc --noEmit` | same | **PASS** | 0 | §2b |
| Unit / component | `npm run test` (vitest, guarded by `check_vitest_ran.mjs`) | same | **PASS — 114 test files, all passed** | 0 | §3 |
| Build | `npm run build` (`tsc && vite build`) | same | **PASS** — 2742 modules, 16.77 s | 0 | §4 |
| Bundle budget | (build plugin output) | same | **PASS — app entry 113,109 B gzip / 125,000 B (90.5 %)** | 0 | §4 |
| CSS minify warnings | (build output) | same | **0** (baseline: 1) | — | §4 |
| Dead code | `npm run deadcode` (knip) | same | **PASS** | 0 | §5 |
| Contrast audit | `.venv/Scripts/python.exe -I …/contrast_audit.py` | Python 3.12.10 | **PASS — every asserted pair meets threshold** | 0 | §6 |
| Browser E2E | `CI=1 E2E_API_PORT=8100 E2E_WEB_PORT=5273 npx playwright test --project=chromium smoke visual` | self-contained harness: own seeded throwaway SQLite, own API, own Vite | **PASS — 68 passed, 0 failed, 5.4 m** | 0 | §7 |
| Visual regression | (within the above) | 5 screens × light/dark × bn/en × 360/768/1280 | **PASS — 60/60 baselines, no re-baselining** | 0 | §7 |
| Accessibility (automation) | axe specs exist; **not re-run this delivery** | — | **NOT RUN** | — | `ACCESSIBILITY-REPORT.md` |
| Accessibility (manual AT) | — | — | **NOT RUN** — no real screen-reader pass | — | same |
| Keyboard / reflow / screen-reader / resilience specs | exist (≈50 tests) | — | **NOT RUN** this delivery | — | `TEST-STRATEGY-AND-MATRIX.md` §7 |
| Android / emulator / device | — | — | **BLOCKED** — no `java`/`gradle`/`adb` | — | `AGENTS.md` §13 |
| Performance | build + bundle measurements only | — | **PARTIAL** — lab only, no field data, no Lighthouse run | — | `PERFORMANCE-REPORT.md` |
| Security review | diff review by an independent `security-reviewer` | — | **PASS for the changed surface** — 0 defects in 8 categories, 3 lower-severity items carried | — | `FRONTEND-SECURITY-REVIEW.md` |
| Independent code review | independent read-only reviewer | — | **11 findings, all dispositioned** | — | `REGRESSION-AND-INDEPENDENT-REVIEW.md` |

### 3.1 Baseline vs final — like for like

| Gate | Baseline (`03dfe21`) | Final | Delta |
|---|---|---|---|
| Format | exit 0 | exit 0 | — |
| Lint | exit 0 | exit 0 | — |
| Unit test files | 113 passed | **114 passed** | +1 file (new motion guard), 0 failures either run |
| Build | exit 0 | exit 0 | — |
| App entry (gzip) | 112,989 B | **113,109 B** | **+120 B** (+0.1 %), still 90.5 % of the 125,000 B ceiling |
| CSS minify warnings | 1 | **0** | fixed |
| knip | exit 0 | exit 0 | — |
| Contrast audit | **exit 1** (3 failures) | **exit 0** | fixed |
| Browser E2E | 217/0/14 junit (recorded chromium baseline) | **68/68, 0 failed** on the smoke+visual scope | — |

**No baseline failure was excused, and no new failure was introduced.**

## 4. Findings fixed

Full detail with evidence in `RISK-REGISTER.md`.

| ID | Sev | Defect | Fixed by |
|---|---|---|---|
| R-01 | **P1** | Contrast guards read only the first of four token blocks; 11 light + 6 dark tokens unasserted; latent trap where a colliding name would silently break dark mode | new shared `cssTokens.ts`; 12 → 27 tests; `blockCounts()` regression guard |
| R-02 | **P1** | Hero prompt placeholder measured **4.24:1** (< 4.5:1) on the most prominent input | `--hero-placeholder` `#6b7a66` → `#525c4d` (**6.51:1**); guard negatively demonstrated at 4.242 |
| R-03 | **P1** | A failed school-invite fetch rendered an **empty list** — a lie an admin would act on | `invitesFailed` + `LoadError` + retry; test negatively demonstrated |
| R-04 | **P2** | Placeholders were unguarded product-wide; every input fell through to the UA colour inside the dark surface | `--placeholder` role + one global `::placeholder` rule with `opacity: 1`; browser-verified |
| R-05 | **P2** | Progress-ring track measured **1.21 / 1.16:1** — the empty arc, i.e. how you read the proportion, was invisible | track → `var(--line-strong)` (**3.54 / 3.46:1**), reusing an already-asserted token |
| R-06 | **P2** | A failed offline-copy delete was completely silent | localized toast + 2 tests |
| R-07 | **P2** | Reduced motion neutralised duration but left 15 `animation-delay`s, holding children invisible up to ~340 ms; and collapsed `infinite` loops to ~1000 restarts/s | delay/iteration resets + new `reducedMotion.test.ts` (6 tests) |
| R-08 | **P3** | A comment containing `.btn-*/` closed early, gluing `.page-title` into an invalid selector list; the browser dropped the whole rule | comment reflowed; rule parses; CSS warnings 1 → 0 |
| R-09 | **P3** | Two `@keyframes voice-pulse`; the later silently killed the recording ripple's expansion | renamed to `voice-blink` |
| R-10 | **P3** | Dead `--glass-bg` dark re-declaration (byte-identical) | removed |
| R-11 | **P3** | Per-question accept button carried the bulk "Accept all" label | `qpAcceptOne`; **plus** the badge at the same file fixed to `qpReviewed` |
| R-12 | **P3** | Resend-verification was `<a href="/forgot">` with an intercepted click — middle-click reached the wrong page, and it announced as a link | now a `Button`; test asserts role, `type="button"`, and that it cannot submit |
| IR-01 | **P1** | **My own defect:** the R-11 rename broke `qpapers.test.tsx`, which then silently re-pointed at the *bulk* button — and I reported it as passing | selector repaired + new guard keeping single and bulk accept separately addressable |
| IR-02 | **P2** | **My own defect:** `LoginPage.tsx` grew past its 353-line ratchet | handler extracted; file now **350 lines**, ratchet untouched |
| IR-03 | **P2** | **My own defect:** two unused exports in the new helper turned knip red | removed |
| IR-06/07 | P3/P2 | A latent cascade trap in the helper; the motion fix had no test of its own | `tokenNamesByBlock()` guard; dedicated motion test file |

## 5. Functional parity

| Metric | Actual result |
|---|---:|
| Discovered features (capability rows) | **~200** |
| Features in register | **~200 / ~200 = 100 %** |
| Features with a post-renovation positive-path functional PASS | **not established for all** (≈3 critical journeys + 8 smoke journeys proven; ≈190 rows covered by register + unit suite + sweeps only) |
| Critical journeys PASS | **3 / 3 driven in a browser** |
| Smoke journeys PASS | **8 / 8** |
| Routes smoke-visited post-renovation | **partial** — 5 screens × 4 variants × 3 viewports + the smoke routes; not a per-route visit of all 23 addressable pages |
| Visual baselines PASS | **60 / 60, no re-baselining** |
| Permission-negative tests PASS | **not measured this delivery** |
| Features removed / disabled / orphaned / mocked | **0** |
| New unresolved regressions | **0 known** |

Every change was traced to the register and to a preservation test; the change→test matrix is
`TEST-STRATEGY-AND-MATRIX.md` §3 and the per-change parity table is `FEATURE-PARITY-REPORT.md` §4.

## 6. What was deliberately not done, and why

| Item | Reason |
|---|---|
| Collapse the two button vocabularies (7 raw call sites) | `formControlBoundary.test.ts` asserts `button.secondary` as a live selector, so retiring it means rewriting an accessibility guard in the same change — a bigger and riskier diff than any accepted slice, touching four role dashboards |
| Unify the three parallel stat layouts (86 raw sites vs 5 `<Stat>` uses) | Highest-churn change in the codebase; overlaps the same legacy layer as the button work; invalidates most visual baselines at once |
| Subtract the decorative layer (3 blurred "aurora" blobs on a 16 s loop, a masked page weave, a shine sweep on every button hover, duplicated tile gloss, 86 `box-shadow` declarations) | The one change most visible to a user, and the one that invalidates nearly all 60 baselines simultaneously. Doing it without completing the capture-review-rebaseline cycle would produce exactly the "attractive diff, green report, no real verification" outcome the task forbids. **Top recommendation.** |
| Add confirmations to four destructive actions | The feature lock names "confirmations" and "submission behavior" explicitly, and `savedNotes.test.tsx` asserts the current single-step behaviour — so it is intended, not accidental. **R-13**, owner decision |
| Widen `/school` to platform `admin` | `App.tsx` gates it to `school_admin` while the page documents both. Widening a frontend gate is the frontend-only-authorization trap. **R-14** |
| Add school-student pagination | A **new capability**, which the lock forbids under a renovation. **R-18** |
| Fix the Makefile `seed` path bug | Build tooling outside this frontend scope; worked around. **R-19** |
| Author a `CHANGELOG.md` entry | `AGENTS.md` §11 assigns the changelog to the Principal Architect only, and `check_changelog.py` gates it. **Handover item** |

## 7. Files changed

**Product code (6 files):**

| File | Change |
|---|---|
| `apps/web/src/styles.css` | comment reflow + `.page-title` restored; `--hero-placeholder` value; `--placeholder` role + global `::placeholder`; `.ring` track; reduced-motion block; `--glass-bg` duplicate removed; `voice-pulse` → `voice-blink` |
| `apps/web/src/i18n.ts` | +3 keys in both dictionaries: `offlineDeleteFailed`, `qpAcceptOne`, `qpReviewed` |
| `apps/web/src/pages/LoginPage.tsx` | resend control anchor → `Button`; handler extracted (net −3 lines vs baseline) |
| `apps/web/src/components/admin/SchoolsCard.tsx` | `invitesFailed` state; `LoadError` + retry in the invite table |
| `apps/web/src/components/OfflineLibrary.tsx` | failed delete now reports |
| `apps/web/src/components/teacher/QPaperReviewPanel.tsx` | per-question label + reviewed badge |

**Tests (7 files):** new `src/test/cssTokens.ts`, new `src/test/reducedMotion.test.ts`; modified
`contrastTokens.test.ts`, `formControlBoundary.test.ts`, `qpapers.test.tsx`,
`admincenter.test.tsx`, `offlineLibraryCopy.test.tsx`, `login.test.tsx`.

**Documentation:** 21 files under `docs/frontend-renovation/` plus
`evidence/accessibility/contrast_audit.py` and the R-08 repro.

**Not changed, verified by an independent reviewer:** `package.json`, `package-lock.json`,
`vite.config.ts`, eslint config, `apps/api/**`, `.env*`, CI workflows, Capacitor/Android config,
`src/api.ts`, `src/types.ts`, `src/AuthContext.tsx`, `App.tsx`, `src/lib/roles.ts`.

## 8. Limitations and handover

### Not functionally verified
~190 capability rows: no per-feature end-to-end execution. Accepting forms, every filter/sort
control, every export/download, the teacher content-generation flows, the admin console's
destructive paths, and the parent/guardian journeys are covered by unit/component tests and by
the register, **not** by browser journeys in this delivery.

### Environment blockers
- **Android/WebView/device: BLOCKED.** No `java`, `gradle`, `adb`.
- **A dev API on `:8000` serves a different SQLite file than `make seed` writes.** Worked
  around by running Playwright self-contained; the owner's services were left untouched. Worth
  a look — it will mislead the next person who expects `make seed` to make browser login work.
- **`make seed` is broken** as written (`../apps/web` from `apps/api`) — **R-19**.

### Baseline failures remaining
None in the web gate set. One baseline *defect* (the malformed CSS selector) was found and
fixed.

### Not present / not run
axe sweep (24 browser tests), `keyboard`, `reflow`, `screen-reader`, `resilience`, `qa-flows`,
`w2-*` and the Firefox/WebKit `engines` specs; Lighthouse; `test:coverage`; the API gate set;
the `mobile-chromium` project.

### Unmeasured
Field LCP/INP/CLS (no RUM source), lab LCP/INP, long tasks, long-conversation scroll/memory,
data-heavy table rendering at scale, throttled-network behaviour.

### Open findings for the owner
`R-13` four unconfirmed destructive actions · `R-14` `/school` role gate vs its doc comment ·
`R-15` ring arc-vs-track 1.55/2.81:1 (needs a three-level gauge) · `R-16` `.card` mixed border
1.22/1.17:1 · `R-17` `on_disable_note_code` can surface as machine text · `R-18` school
students unpaginated · `R-19` broken `make seed` · `R-20` resend drops focus on success ·
`IR-11` no `CHANGELOG.md` entry.

### Rollback
Git is the rollback path; nothing is committed, stashed or branched.
`git checkout -- apps/web/src` plus deleting the untracked `src/test/cssTokens.ts` and
`src/test/reducedMotion.test.ts` restores the baseline exactly. No migration, schema,
dependency, lockfile or configuration change exists, so there is no data-side rollback.

### Next steps, in recommended order
1. **Wave 3.3** — subtract the decorative layer, with the full 60-snapshot
   capture-review-rebaseline cycle. Highest visible value; needs a full cycle, not a patch.
2. **Wave 3.1/3.2** — collapse the button and stat vocabularies, rewriting
   `formControlBoundary.test.ts` in the same change.
3. Add `CHANGELOG.md` (Principal Architect) and the missing school-student pagination.
4. Relocate the tenth `ENGINES`/`reflow`/`screen-reader` specs into the standard gate run so
   the next delivery does not have to scope them out.
5. Fix `make seed`, and reconcile the dev API's database with what the seed writes.

## 9. Verification-integrity note

This delivery contains an instance of the failure mode these reports exist to prevent. I
renamed a control, broke an existing test, read past the failure because my output filter hid
it, and wrote a passing result into the execution log. An independent reviewer caught it.

The claim is corrected in place in `EXECUTION-LOG.md` §Wave 2 and
`TEST-STRATEGY-AND-MATRIX.md` §3 rather than edited out, and it is recorded as `IR-01` in
`REGRESSION-AND-INDEPENDENT-REVIEW.md`. Two further defects of mine were caught the same way
(`IR-02` ratchet breach, `IR-03` dead exports), and my own lint gate caught a fourth
(unnecessary type assertions) before the final run.

**Everything else in this report was produced by a command whose output is recorded.**
