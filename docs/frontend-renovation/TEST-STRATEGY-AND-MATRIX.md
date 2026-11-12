# Test Strategy and Matrix — Bangla GPT frontend renovation

## 1. Existing test estate (measured, not assumed)

The repository already had a substantial suite before this renovation. Nothing new was
introduced at the framework level — no second test runner, no new dependency
(`AGENTS.md` §4 and the master prompt §11.1 "use existing test tools first").

| Layer | Tool | Baseline size | Guarded by |
|---|---|---|---|
| Format | Prettier | whole `src` | `npm run format:check` |
| Lint | ESLint 9 (`--max-warnings 0`) | whole `src` | `npm run lint` |
| Typecheck | `tsc` (strict, `noUnusedLocals`, `noUnusedParameters`) | whole `src` | part of `npm run build` |
| Unit / component | Vitest 4 + Testing Library (jsdom) | **113 files / 479 tests** | `npm run test` → `scripts/check_vitest_ran.mjs` so an incomplete run cannot exit 0 |
| Dead code | knip | whole `src` | `npm run deadcode` |
| Browser E2E | Playwright 1.64, 22 spec files | 217 tests in the recorded chromium run (14 config-gated skips) | `npx playwright test` |
| Visual regression | Playwright `toHaveScreenshot` | **60 PNG baselines** (`5 screens × {light,dark} × {bn,en} × {360,768,1280}`), `maxDiffPixelRatio 0.05` | `e2e/visual.spec.ts` |
| ARIA regression | Playwright `toMatchAriaSnapshot` | 3 YAML baselines | `e2e/screen-reader.spec.ts` |
| Browser a11y | axe-core via Playwright | 24 tests, 4 theme×language variants, public + all five role routes | `e2e/axe.spec.ts` — fails on serious/critical only |
| jsdom a11y | axe-core | 3 sweeps (colour-contrast deliberately disabled — jsdom cannot compute it) | `src/test/axeSweep.test.tsx` |
| Token contracts | hand-rolled, computed from `styles.css` | 3 files | `contrastTokens`, `formControlBoundary`, `w2_i18n_css_typography` |
| Bengali quality | hand-rolled | numeral policy, typography, mixed-script guards | multiple files |
| Build budget | custom Vite plugin | app entry ≤ 125,000 B gzip | build output |
| Lighthouse | `@lhci/cli` in CI | perf ≥ 0.5, LCP ≤ 4000 ms, CLS ≤ 0.1, TBT ≤ 3000 ms, script ≤ 1.2 MB, stylesheet ≤ 160 kB, font ≤ 700 kB, total ≤ 2 MB | `apps/web/lighthouserc.json` |

## 2. Strategy for this renovation

Deliberately **regression-first and additive**. The change set is presentation, feedback,
copy and element-semantics; no handler, API call, permission, validation rule or state
transition was touched. So the strategy is:

1. **Do not weaken or rewrite any existing assertion.** A refactor that moved shared code
   into `src/test/cssTokens.ts` had to preserve every assertion it displaced — verified by
   the independent reviewer, not by me (see `REGRESSION-AND-INDEPENDENT-REVIEW.md`).
2. **Every behaviour-bearing change ships a test in the same change** (`AGENTS.md` §6).
   Four such changes, four new tests (below).
3. **Every new guard must be demonstrated to fail.** A guard nobody has seen fail is not
   evidence (`R-22`).
4. **Prefer measuring to asserting** where the claim is numeric: the WCAG ratios live in a
   reproducible script (`evidence/accessibility/contrast_audit.py`) that reads the real
   token values out of `styles.css` rather than hardcoding hexes.

## 3. Change → test matrix

| Change | Prod file | Test(s) added or extended | Positive path | Negative path | Status |
|---|---|---|---|---|---|
| R-01 guards parse all token blocks | `src/test/cssTokens.ts` (new) | `contrastTokens.test.ts` — new `token-block coverage (guard regression)` describe | asserts ≥2 blocks per theme and 11 late-block tokens are merged | **demonstrated**: reverting to an `indexOf` parser drops those tokens | PASS |
| R-02 hero placeholder ratio | `styles.css` | `contrastTokens.test.ts` — `hero prompt placeholder contrast (A11Y)` (3 tests) | ≥4.5:1 across all three `--grad-hero` stops | **demonstrated**: old `#6b7a66` fails at `4.242 < 4.5` | PASS |
| R-04 global placeholder token | `styles.css` | `contrastTokens.test.ts` — `global placeholder token (A11Y)` (2 tests) | rule exists, drives `--placeholder`, `opacity: 1`; ≥4.5:1 on 4 surfaces × 2 themes | exact-selector match (a suffix match on the hero rule would otherwise pass) | PASS |
| R-05 ring track | `styles.css` | `contrastTokens.test.ts` — `progress-ring track contrast (A11Y)` (2 tests) | uses `--line-strong`; ≥3:1 vs `--card` both themes | — | PASS |
| R-05b previously unguarded pairs | `styles.css` | `contrastTokens.test.ts` — `semantic label pairs (A11Y)` (10 cases × 2 themes) | 4.5:1 each | — | PASS |
| R-03 honest invite failure | `SchoolsCard.tsx` | `admincenter.test.tsx` — new test | `LoadError` + retry inside the invite table | **demonstrated**: "Unable to find role=alert" with the old empty-list catch | PASS |
| R-06 honest offline-delete failure | `OfflineLibrary.tsx` | `offlineLibraryCopy.test.tsx` — 2 new tests | failed delete raises the localized toast, row remains; successful delete raises none | — | PASS |
| R-12 resend as an action | `LoginPage.tsx` | `login.test.tsx` — new test | finds it by `role=button`, `type="button"`, calls `resendVerification("a@b.com")` | asserts `queryByRole("link")` is null | PASS |
| R-11 QP single-row label | `QPaperReviewPanel.tsx` | `qpapers.test.tsx` — existing test repaired, **plus** a new `keeps the bulk accept distinct from the single-question accept` | single-question accept posts exactly one decision; bulk posts all | the pre-existing test selected the per-question button by the OLD label, so after the rename it silently pointed at the bulk button and failed. See `REGRESSION-AND-INDEPENDENT-REVIEW.md` **IR-01** — an independent reviewer caught it, not me. | PASS (5/5) after repair |
| IR-04 reviewed badge | `QPaperReviewPanel.tsx` | `qpapers.test.tsx` | badge now `qpReviewed` | — | PASS |
| IR-07 reduced motion | `styles.css` | **new** `reducedMotion.test.ts` (6 tests) | duration, delay and iteration-count reset; `::before`/`::after` covered; scroll instant; non-zero `animation-delay` still exists outside the block so the assertions cannot pass vacuously; live indicators keep a non-motion channel | — | PASS |
| IR-06 cascade trap | `cssTokens.ts` | **new** guard in `contrastTokens.test.ts` | later `:root` disjoint from earlier blocks | **would fail** if a name were declared in both | PASS |
| R-07 reduced motion | `styles.css` | existing `tutorAutoScroll.test.tsx`, `skipLink.test.tsx`, `w2_i18n_css_typography.test.ts` re-run | — | — | PASS |
| R-08 comment/.page-title | `styles.css` | build CSS-warning count 1 → 0; browser check that the rule parses | yes | — | PASS |
| R-09/R-10 duplicates | `styles.css` | (no test referenced either name; verified by grep) | — | — | NOT APPLICABLE |

## 4. Keyboard contracts that must not regress

Twelve cross-cutting behaviours are listed as untouchable in
`FEATURE-LOCK-REGISTER.md` §10. The six roving-nav widgets are covered by
`e2e/keyboard.spec.ts` (7 tests) and unit tests:

| Widget | Keys | Covered by |
|---|---|---|
| Global search combobox | ArrowUp/Down, Home, End, Enter, Escape | `searchBox.test.tsx`, `keyboard.spec.ts` |
| Notification menu | ArrowUp/Down wrap, Home, End, Escape + focus restore, Tab closes | `notificationbell.test.tsx` |
| Chapter workspace tablist | Arrow ←→↑↓, Home, End, roving tabindex | `keyboardContracts.test.tsx` |
| Quiz hub tabs | Arrow ←→ | `assessmentTabs.test.tsx` |
| Quiz option radio group | Arrow ↓→↑←, Home, End | `keyboardContracts.test.tsx` |
| Conversation rename input | Enter commits, Escape cancels, blur commits | `conversationChip.test.tsx` |
| IME-guarded Enter on every ask/send input | `nativeEvent.isComposing` — **Android Bangla IME** | `tutorInputContracts.test.tsx` |

## 5. Coverage denominators and what this delivery actually reached

| Measure | Target for `COMPLETED — VERIFIED` | This delivery |
|---|---|---|
| Inventory coverage (features in register ÷ discovered) | 100 % | **100 %** — ~200 capability rows across 25 routes |
| Static gates (format / lint / typecheck / build / knip) | all pass | **all pass** |
| Unit / component | all pass | **see `FINAL-DELIVERY-REPORT.md`** |
| Route smoke, post-renovation | 100 % of accessible routes | **partial** — `crawl` + `smoke` + `visual` cover the representative set; not every one of the 23 addressable pages was individually smoke-visited |
| Functional positive-path per feature | 100 % | **not reached** — no per-feature functional PASS was executed for all ~200 rows |
| Permission negative paths (P0/P1) | pass | **partial** — `e2e/session.spec.ts`, `qa-flows.spec.ts` and `w2-session.spec.ts` cover session/permission behaviour; route-guard negatives were not exhaustively re-run |
| Visual regression | reviewed | 60 baselines present; deltas reviewed where the harness completed |
| Browser axe | serious/critical = 0 | see `ACCESSIBILITY-REPORT.md` |
| Android / native | required if in product scope | **BLOCKED** — no `java`/`gradle`/`adb` on this machine (`AGENTS.md` §13) |

**Therefore the honest verdict is not `COMPLETED — VERIFIED`.** The full per-feature functional
matrix was not executed; quantifying exactly what was and was not run is the job of
`FEATURE-PARITY-REPORT.md` and `FINAL-DELIVERY-REPORT.md`.

## 6. Running the evidence yourself

```bash
# Static + unit (from the repository root's apps/web)
cd apps/web && npm run format:check && npm run lint && npm run test && npm run build && npm run deadcode

# Reproducible contrast audit (reads the real token values; exit 1 on a breach)
.venv/Scripts/python.exe docs/frontend-renovation/evidence/accessibility/contrast_audit.py

# Browser E2E. Run it SELF-CONTAINED so it seeds its own database:
#   the harness sets reuseExistingServer:true outside CI, so if anything already
#   answers on the default API port it is adopted and its seeding is SKIPPED.
cd apps/web && CI=1 E2E_API_PORT=8100 E2E_WEB_PORT=5273 npx playwright test --project=chromium

# Visual baselines only (Windows-only file: it skips on other platforms by design)
cd apps/web && CI=1 E2E_API_PORT=8100 E2E_WEB_PORT=5273 npx playwright test --project=chromium visual
```

## 7. Explicitly not tested

- No mobile/native device or Android emulator run — impossible on this machine.
- No field performance data — no RUM source exists; all numbers are lab-only.
- No load, soak, or traffic-capacity testing. **Nothing here supports a national-scale
  capacity claim.** Frontend evidence cannot establish backend reliability.
- No usability testing with real users, and no claim of any.
- No screen-reader session with a real assistive technology. ARIA snapshots and axe results
  are not a substitute for an NVDA/TalkBack pass.
