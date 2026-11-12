# Visual QA Report — Bangla GPT frontend renovation

## 1. Harness and conditions

| Item | Value |
|---|---|
| Command | `CI=1 E2E_API_PORT=8100 E2E_WEB_PORT=5273 npx playwright test --project=chromium smoke visual` |
| Why those ports | `playwright.config.ts` sets `reuseExistingServer: !process.env.CI`. Outside CI the harness **adopts** any server already answering on the default port and **skips its own seeding** — which produced two spurious "Email or password is incorrect" failures on the first attempt. `CI=1` forces fresh servers; the non-default API port sets `DIRECT_API`, so the harness starts and seeds its **own** throwaway SQLite database. The owner's running API and dev server were left untouched. |
| Browser | Chromium via installed Playwright `chromium-1248` |
| Viewports | 360 × 800, 768 × 1024, 1280 × … (the `visual.spec.ts` set) |
| Themes / languages | light and dark × bn and en — 4 variants per screen |
| Screens | `welcome`, `login`, `student-home`, `student-tutor`, `teacher-home` |
| Baseline comparison | `expect(page).toHaveScreenshot()`, `maxDiffPixelRatio: 0.05`, `animations: "disabled"`, `caret: "hide"`, 60 PNG baselines |
| Accounts | the read-only seeded accounts (`student2@e2e.test`, `teacher2@e2e.test`) so screens are deterministic |

## 2. Result

```
68 passed (7.9m)
```

**68 of 68 passed, 0 failed, 0 flaky.** That is all 8 smoke journeys plus all 60 visual
baselines.

### 2.1 Smoke journeys (real user flows, real API, mock LLM provider)

| # | Journey | Result |
|---:|---|---|
| 1 | A student signs in, is routed to the student home and can log out | **PASS** |
| 2 | A guardian-consented student registers and lands on the student home | **PASS** |
| 3 | A student asks the tutor and gets a streamed mock answer | **PASS** |
| 4 | An out-of-corpus question is **refused** with the grounding message | **PASS** |
| 5 | A student completes a quiz attempt end to end | **PASS** |
| 6 | A teacher signs in and sees the teacher dashboard | **PASS** |
| 7–8 | Remaining smoke journeys (parent/admin coverage) | **PASS** |

Journey 4 is the one worth naming: it asserts that a refusal is a **first-class outcome**,
not a failure to be worked around. This renovation did not touch the grounding path, and the
assertion still holds — which is the evidence that the tutor's honesty contract survived.

### 2.2 Visual baselines — and what "all passing" actually means

All 60 baselines passed **without re-baselining**. That is a genuinely informative result and
it deserves an honest reading in both directions:

**What it proves.** The renovation did not move the rendering of five representative screens
across four theme/language variants and three viewports. Since this change set touched
`styles.css` globally (a new `::placeholder` rule, a changed ring track, a restored
`.page-title` rule, a rewritten reduced-motion block, a removed token), a clean sweep is
meaningful evidence that nothing leaked into unrelated surfaces.

**What it does not prove.** The comparator tolerance is `maxDiffPixelRatio: 0.05`. A
placeholder colour change and a thin progress-ring track are well under 5 % of a page's pixels;
a real, deliberate change of exactly that kind would **not** trip this gate. So:

> **The relevant verification for R-02 and R-05 is the computed contrast ratio and the parsed
> CSS rule, not the pixel diff.** Both were established independently — the ratios by
> `evidence/accessibility/contrast_audit.py` reading the real token values, and the rules by
> evaluating the live stylesheet in a browser.

Recording this matters because "60 visual tests passed" is the kind of number that invites
over-claiming. It is evidence of *no unintended change*, not evidence that the intended
change happened.

## 3. Direct browser verification of the specific fixes

Beyond the harness, the running application was inspected in a real browser (Playwright MCP
against `http://localhost:5173` with the project's dev server on the seeded `dev.db`).

| Fix | Method | Result |
|---|---|---|
| **R-04** global placeholder token | Created a probe input with no rule of its own; read `getComputedStyle(probe, '::placeholder')` | `color: rgb(93, 107, 87)` — i.e. `--placeholder` (= `--muted`) — at `opacity: 1`. Exactly two `::placeholder` rules parse: the new global one and the hero-specific one. **Verified** |
| **R-08** `.page-title` parses again | Enumerated parsed CSS rules containing `page-title` in `document.styleSheets` | `.page-title { font-size: var(--fs-2xl); font-weight: 700; margin: 0 0 var(--space-4); }` — a **valid** rule now parses. Before the fix the browser parsed **zero** rules for that class (`rulesFound.probe = 0`) because the whole rule was dropped as part of an invalid selector list. **Verified** |
| **R-08** root cause | Loaded a minimal repro (`evidence/browser-console-network/invalid-selector-repro.html`) over local HTTP with the exact emitted selector, plus a valid control selector | Probe: `rulesFound = 0`, fell back to the UA `h1` margin (`21.44px`). Control: `rulesFound = 1`, applied `24px`. **Definitively confirmed** the browser drops the entire rule |
| **R-08** real severity | Read the base `h1` rule at `styles.css:380` | It already sets `font-size: var(--fs-2xl)`, so the true delta was the bottom margin only (`0.4em` ≈ 10.9 px vs `--space-4` = 16 px). **Severity corrected P1 → P3** |
| **R-13** a page-level visual check | Screenshot `evidence/final/01-login-bn-light-1440.png`, read back and inspected | Login page renders correctly in Bangla light at 1440: brand lockup, three trust rows, both CTAs, the sign-in card, and the footer. No layout, clipping, or glyph defect observed |

## 4. Objective design rubric

Applied to the representative screens that were actually captured. Scores are a transparent
heuristic review, **not** a UX metric. Reference: the login screenshot above and the 60
baseline images.

| Dimension | Score | Observation |
|---|---:|---|
| Task clarity | 4 | On `/login` the primary action ("লগইন") is unambiguous, the two inputs are labelled, and "পাসওয়ার্ড ভুলে গেছেন?" / "নিবন্ধন" sit clearly subordinate. |
| Information hierarchy | 4 | Brand lockup → three value props → CTAs on the left; a single sign-in card on the right. Supporting copy is visibly secondary. |
| Bengali-first readability | 4 | Bangla headings and body render with correct conjuncts at the captured size; line-height is comfortable; no tracking artefacts. Judged from the capture and the enforced CSS floors only — **not** a native-device glyph review. |
| Consistency | 4 | Reuses the same card, button and field vocabulary as the rest of the product. Deductions come from the duplication recorded in `COMPONENT-INVENTORY.md` §3 — two button vocabularies and three stat layouts still coexist. |
| Responsive usability | 3 | The captured 1440 view is sound, and the 60 baselines pass at 360/768/1280. Not scored higher because the file mixes mobile-first and desktop-first media syntax across layers, and the 760 px tier is fragmented across four blocks. |
| Accessibility | 4 | Focus-visible, labelled inputs, skip link, `role="alert"` on errors, contrast now asserted for the previously-unguarded pairs. Not 5 because no real assistive-technology pass was performed. |
| Interaction quality | 4 | Honest loading/empty/error/retry surfaces throughout (`LoadError`, 19 uses), and this renovation removed two places where the UI reported a successful state it had not achieved (R-03, R-06). |
| Visual integrity | 3 | The product has a real identity — NCTB/green brand, Bangla-first type, restrained surfaces. But decoration still substitutes for hierarchy in places: three drifting blurred "aurora" blobs behind the home hero on a 16 s loop, a shine sweep on every button hover, the same inset gloss copy-pasted into four tile rules, and 86 `box-shadow` declarations. **Recorded, deliberately not changed** — see §5. |

No dimension scored 1 or 2, so no dimension compels a fix before acceptance on these screens.

## 5. The one thing this report will not do

The direction set out in `DESIGN-DIRECTION.md` §3 item 2 was "subtract decoration that carries
no information" — the aurora blobs, the masked page-background weave, the per-button shine
sweep, the duplicated tile gloss, the collapsed shadow scale.

**That work is not done.** It is the change most likely to be visible to a user, and it is
also the one that invalidates nearly all 60 visual baselines simultaneously, requiring a full
capture-review-rebaseline cycle. Doing it without completing that cycle would produce exactly
the outcome the task forbids: an attractive diff with a green-looking report and no real
verification behind it. It is deferred to Wave 3.3 with the reason recorded in
`IMPLEMENTATION-PLAN.md`, and it is the top recommendation in `FINAL-DELIVERY-REPORT.md`.

## 6. Not covered

| Item | Status |
|---|---|
| Visually confirming each of the 23 addressable routes | **PARTIAL** — `smoke` drives the critical journeys and `visual` covers 5 representative screens; there is no per-route screenshot for every page |
| Error / empty / streaming states captured as images | **NOT RUN** — the states are exercised by unit tests and by `resilience.spec.ts`, but no screenshot set was captured for them |
| `e2e/axe.spec.ts` (24 a11y sweeps), `keyboard`, `reflow`, `screen-reader`, `resilience`, `qa-flows`, `w2-*` specs | **NOT RUN in this delivery** — they exist and are green in the recorded CI baseline, but this run was scoped to `smoke` + `visual` |
| Android / WebView | **BLOCKED** — no `java`, `gradle` or `adb` here. Browser viewport emulation is **not** reported as native testing |
| Dark-theme and English variants inspected by eye | **PARTIAL** — they are covered by the passing baselines; only the Bangla/light login capture was read back and reviewed manually |
