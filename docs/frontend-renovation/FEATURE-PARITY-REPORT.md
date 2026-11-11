# Feature Parity Report — Bangla GPT frontend renovation

This is the report the master prompt §11.8 asks for, and it is the document that decides the
verdict. It reports **what was actually executed**, not what the code appears to do.

---

## 1. Parity table

Every count below is derived from a command that was run, or is marked as not run. Nothing is
estimated.

| Metric | Actual result | Basis |
|---|---:|---|
| Discovered features (capability rows) | **~200** | Full reads of 22 page modules + 30 components, each row carrying a `file:line` |
| Features in register | **~200 / ~200 = 100 %** | `FEATURE-LOCK-REGISTER.md` |
| Routes discovered | **25 declared entries** (23 addressable pages + 1 redirect + 1 catch-all) | `ROUTE-AND-PAGE-INVENTORY.md` |
| Roles discovered | **5** — student, teacher, parent, admin, school_admin | `App.tsx` gates + `ROLE_HOME` |
| **Features with a post-renovation positive-path functional PASS** | **not established for all** | No per-feature functional execution was run across all ~200 rows. This is the single largest gap in this delivery. |
| Critical journeys PASS | **3 of 3 driven in a browser** — sign-in/routing/logout, streamed grounded answer + refusal, full quiz attempt | `e2e/smoke.spec.ts` 1/3/4/5, **PASS** |
| Smoke journeys PASS | **8 of 8** | `e2e/smoke.spec.ts`, **68/68 e2e total, 0 failed, 7.9 m** |
| Routes smoke-visited post-renovation | **partial** — representative screens via `visual` (5 screens × 4 variants × 3 viewports = 60 snapshots) plus the smoke journeys' routes. **Not** a per-route visit of all 23 addressable pages. | `VISUAL-QA-REPORT.md` §2 |
| Visual baselines PASS | **60 / 60** | `e2e/visual.spec.ts`, run within the same 68 |
| Permission-negative tests PASS | **not measured this delivery** | Route-guard negative paths were not re-executed for every role × route pair. Server-side tenancy and role rejection are covered by the API's own tests, which were not run here. |
| Accessibility automation | **not re-run** | `e2e/axe.spec.ts` (24 sweeps) and the jsdom sweeps exist and were green in the recorded baseline; they were not part of this run |
| Unit / component tests | **see `FINAL-DELIVERY-REPORT.md` test table** | `npm run test` |
| Features removed, disabled, orphaned or mocked | **0** | Every change in the diff is presentation, feedback, copy or element semantics. No handler, API call, argument, permission, validation rule or state transition was altered. |
| New unresolved regressions | **0 known** | All 68 browser tests pass; all static gates pass; every behaviour-bearing change carries a test that was negatively demonstrated to catch the old behaviour |
| Android / native | **BLOCKED** | No `java`, `gradle` or `adb` on this machine (`AGENTS.md` §13) |

## 2. What "100 % register coverage" does and does not mean

**It means** every capability discovered by reading the code appears in the register with its
entry point, action, states, role gate and a `file:line` reference — so nothing was silently
dropped from scope, and a later reviewer can check any row against the source.

**It does not mean** every capability was exercised. The register is a *contract*, not
evidence. The master prompt is explicit that a row existing is not a claim that the feature
works (`FEATURE-LOCK-REGISTER.md` §Evidence status says so at the top of the file).

## 3. Why the functional denominator was not closed

Stated plainly rather than dressed up: closing it means driving ~200 capabilities through
their real entry points with the right synthetic role, verifying inputs, validation,
permission, API request/response, resulting state, and the relevant loading/success/error
paths — the master prompt §11.2's ten-step procedure, per feature. Doing that honestly is a
multi-day harness effort for a product with 25 routes and 5 roles. What was executed instead:

- **Every static gate**, before and after (format, lint, typecheck inside the build, build,
  knip) — both runs green.
- **All 8 smoke journeys** in a real browser against a real seeded API.
- **All 60 visual baselines** across 5 screens × 4 theme/language variants × 3 viewports.
- **Every capability the renovation itself touched**, with a test that was demonstrated to
  fail against the pre-change code (the four behaviour-bearing changes in §4).
- **~150 unit/component test files** as the regression net over the untouched surface.

That is real verification of the changed surface and of the critical journeys, and it is not
verification of every feature. The verdict reflects that difference.

## 4. Per-change parity evidence (the part that *is* closed)

| Change | Feature IDs affected | Contract preserved? | Positive test | Negative test (demonstrated to fail pre-change) |
|---|---|---|---|---|
| R-01 guard parser | none — test-only | n/a | 27 contrast tests + 3 boundary tests pass | reverting to the `indexOf` parser drops the 11 late-block tokens |
| R-02 hero placeholder | `STU-HOME-001` | yes — colour only | ≥4.5:1 on all three gradient stops | old `#6b7a66` → `4.242 < 4.5` |
| R-03 honest invite failure | `ADM-SCH-003` | yes — the fetch, the endpoint and the success path are unchanged; only the failure rendering is new | `LoadError` + retry inside the invite table | old empty-list catch → `Unable to find role="alert"` |
| R-04 global placeholder | every input-bearing feature | yes — additive single global rule | 4 surfaces × 2 themes ≥4.5:1; browser-verified | exact-selector match guards against a suffix-match false pass |
| R-05 ring track | `STU-HOME-005`, `STU-QUIZ-005`, `TCH-CLASS-009` | yes — colour only | ≥3:1 vs `--card` both themes | — |
| R-06 report failed delete | `STU-LEARN-004` | yes — handler, store call and arguments unchanged; a message was added | failure raises the localized toast, row remains | (see `TEST-STRATEGY-AND-MATRIX.md` §3) |
| R-07 reduced motion | all animated surfaces | yes — media-query behaviour only | existing animation suites pass | — |
| R-08 comment / `.page-title` | `adm`, `parent`, teacher pages | yes — CSS only | rule parses in a browser; build CSS warnings 1 → 0 | minimal repro proved the browser dropped the entire rule before |
| R-09 `@keyframes` rename | voice/recording indicators | yes — restores the intended ripple | no test referenced either name | — |
| R-10 dead token removal | none | yes — value was identical | token still resolves in both themes | — |
| R-11 QP label | `TCH-QPR-003` | yes — same handler, same payload | `qpapers.test.tsx` passes | — |
| R-12 resend as a button | `AUTH-RESEND-001` | yes — same handler, same argument, same outcome | calls `resendVerification("a@b.com")`; `type="button"`; no link role | — |

## 5. Features explicitly known to be less capable than they could be (unchanged on purpose)

These are **not** parity failures — the capability is exactly as it was. They are recorded so
nobody reads the green result as "everything is optimal".

| Feature ID | Observation | Why unchanged |
|---|---|---|
| `SCH-SEC-001` | Fetches `getSchoolStudents(100, 0)` — page 1 only, with no indication that it is truncated | Adding pagination is a **new capability**, which the feature lock forbids under a renovation (**R-18**) |
| `STU-ME-005`, `STU-LEARN-004`, `STU-ME-006`, `ADM-SCH-004` | Four destructive actions take effect with no confirmation | Confirmations are named in the locked contract, and `savedNotes.test.tsx` asserts the current single-step behaviour — so it is intended, not accidental (**R-13**) |
| `SCH-OVR-001` | `/school` is documented as serving "school_admin / admin" but gated to `school_admin` | Whether a platform admin should see it is a permissions decision; widening a frontend gate is the frontend-only-authorization trap (**R-14**) |
| `STU-CHAT-016`/`017` | Ring arc-vs-track contrast is 1.55:1 / 2.81:1; the arc is read by hue | Needs a three-level gauge — a design decision (**R-15**) |
| `SHL-NOTIF-001` | `.notif-badge` is the one surface still using a raw `10px` font size and a `line-height: 1` | Cosmetic, inside a reviewed badge; recorded, not churned |

## 6. Honest bottom line

- **Feature preservation: no evidence of any regression.** 68/68 browser tests pass — including
  all 60 visual baselines without re-baselining, which is meaningful evidence that a global CSS
  change did not leak into unrelated surfaces — and every static gate is green before and after.
- **Feature verification: partial.** Three critical journeys and eight smoke journeys are
  proven end to end; the remaining ~190 capability rows are covered by the register, the unit
  suite and the smoke/visual sweeps, but not by a per-feature functional execution.
- **Therefore:** not `COMPLETED — VERIFIED`. See `FINAL-DELIVERY-REPORT.md` §verdict.
