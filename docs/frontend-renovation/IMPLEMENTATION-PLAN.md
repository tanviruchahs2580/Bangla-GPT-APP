# Implementation Plan — Bangla GPT frontend renovation

Derived from the baseline audit, the design direction and the risk register. Sequencing
follows the master-prompt §1.3 waves, but the wave *contents* are evidence-driven: each
slice traces to a numbered finding (`R-nn` in `RISK-REGISTER.md`), not to a template.

**Scope statement.** This is a repair-and-solidify renovation of a mature frontend, not a
rebuild. The design direction (`DESIGN-DIRECTION.md` §3) explicitly rejects a restyle, and
the feature lock (`FEATURE-LOCK-REGISTER.md`) is authoritative over every change below.

---

## Wave 0 — Discovery and baseline (COMPLETE)

| Slice | Deliverable | Evidence |
|---|---|---|
| 0.1 | Environment, toolchain, repository identity, worktree safety | `BASELINE-AND-REPOSITORY-AUDIT.md` §1–2 |
| 0.2 | Baseline gate capture before any edit | `evidence/test-results/baseline-gates.log` — format/lint/479 tests/build/knip all exit 0 |
| 0.3 | Feature-lock register: 25 routes, 5 roles, ~200 capability rows with `file:line` | `FEATURE-LOCK-REGISTER.md` |
| 0.4 | Route and page inventory, gate model, responsive archetypes | `ROUTE-AND-PAGE-INVENTORY.md` |
| 0.5 | Independent design-system audit + reproducible contrast measurements | `DESIGN-DIRECTION.md` §2, `evidence/accessibility/contrast_audit.py` |
| 0.6 | Design direction with rejected alternatives and an honest unknowns ledger | `DESIGN-DIRECTION.md` |
| 0.7 | Risk register incl. baseline-vs-new classification | `RISK-REGISTER.md` |

**Gate 0 satisfied:** correct repository (`03dfe21`), clean worktree, real stack confirmed
from manifests, five green baseline gates, rollback understood (git is the rollback path;
no branch was switched and no owner work existed to preserve).

## Wave 1 — Foundation and the P1 repairs (COMPLETE)

Ordered by dependency: the guard blind spot is fixed **first**, because it is the reason
several other findings were invisible.

| Slice | Finding | File(s) | Acceptance |
|---|---|---|---|
| 1.1 | R-01 | new `src/test/cssTokens.ts`; rewired `contrastTokens.test.ts`, `formControlBoundary.test.ts` | Guards parse all 4 token blocks; a `blockCounts()` regression guard fails if that regresses. `contrastTokens.test.ts` grows 12 → 27 tests, all pass. |
| 1.2 | R-02 | `styles.css` (`--hero-placeholder`), `contrastTokens.test.ts` | Placeholder ≥4.5:1 against the fill over **all three** `--grad-hero` stops. Guard negatively demonstrated: old `#6b7a66` fails at 4.242. |
| 1.3 | R-04 | `styles.css` (`--placeholder` role + global `::placeholder`) | ≥4.5:1 on `card`/`card-2`/`bg-elev`/`bg` in both themes; `opacity: 1` asserted. Browser-verified. |
| 1.4 | R-05 | `styles.css` (`.ring` track) | ≥3:1 vs `--card` both themes; reuses `--line-strong` so it joins an existing asserted contract. |
| 1.5 | R-07 | `styles.css` (reduced-motion block) | `animation-delay`/`transition-delay` reset to 0; `animation-iteration-count: 1` so collapsed `infinite` loops do not spin. |
| 1.6 | R-08 | `styles.css` (comment + `.page-title`) | Build CSS warnings 1 → 0; rule parses in a real browser. |
| 1.7 | R-09, R-10 | `styles.css` | Colliding `@keyframes` renamed; dead `--glass-bg` override removed. |

**Gate 1 satisfied:** feature register reconciled against code and routes; no route or
feature silently out of scope; format + lint + build re-run green after each slice.

## Wave 2 — Trust repairs (COMPLETE)

Chosen ahead of further visual work because a UI that lies about the state of the system is
worse than one that is merely plain.

| Slice | Finding | File(s) | Acceptance |
|---|---|---|---|
| 2.1 | R-03 | `components/admin/SchoolsCard.tsx`, `admincenter.test.tsx` | A failed invite fetch shows `LoadError` + retry inside the invite table, never an empty list. Test negatively demonstrated ("Unable to find role=alert" without the fix). |
| 2.2 | R-06 | `components/OfflineLibrary.tsx`, `i18n.ts`, `offlineLibraryCopy.test.tsx` | Failed delete raises a localized toast; success raises none. Row remains so the retry the message asks for is possible. |
| 2.3 | R-11 | `components/teacher/QPaperReviewPanel.tsx`, `i18n.ts` | Per-question action labelled `qpAcceptOne`, not the bulk `qpReviewAll`. |
| 2.4 | R-12 | `pages/LoginPage.tsx`, `login.test.tsx` | Resend-verification is a `type="button"` control that announces as an action and cannot submit the form; behaviour unchanged. |

## Wave 3 — Deferred, with reasons (NOT DONE)

These were planned in `DESIGN-DIRECTION.md` §3 as "unify the duplicated primitives" and are
**not** completed in this delivery. They are deferred rather than dropped, and are reported
as such.

| Slice | Target | Why deferred |
|---|---|---|
| 3.1 | Collapse the two button vocabularies: migrate 7 raw `button.primary` / `.secondary` / `.small` call sites (`AppShell.tsx:92`, `ForgotResetPage.tsx:89,124,179`, `ParentDashboard.tsx:149`, `AdminDashboard.tsx:153,163`) to the `Button` primitive, then delete `styles.css:3076-3112`. | `formControlBoundary.test.ts:107` asserts `button.secondary` **as a live selector**. Retiring the vocabulary means rewriting an accessibility guard in the same change — a bigger, riskier diff than any Wave 1/2 slice, and one that touches 4 role dashboards including the parent and admin surfaces. Deferred to a dedicated wave rather than rushed at the edge of this one. |
| 3.2 | Unify the three parallel stat layouts (`.stat` at 1135, `.stat-row > div` at 3141, `.landing-stats > div` at 4735) behind one contract; migrate 86 raw `className="stat…"` sites against 5 `<Stat>` uses. | Highest-churn change in the codebase. Not startable safely without the button work above (they overlap in the same legacy compat layer at `styles.css:3054-3112`), and it would invalidate most of the 60 visual baselines at once. |
| 3.3 | Subtract the decorative layer (3 aurora blobs + `aurora-drift`, the masked `body::after` weave, the per-button `--grad-shine` sweep, the four duplicated tile glosses, collapse the 86-declaration shadow scale to the three tokens that exist for it). | This is the one item that would invalidate nearly every visual baseline simultaneously. Doing it *and* verifying it properly needs the full 60-snapshot review cycle end to end; doing it half-verified would be exactly the "attractive but unverified" outcome the prompt forbids. Recorded as the recommended next wave. |

## Wave 4 — Verification (IN PROGRESS at time of writing)

| Slice | Status |
|---|---|
| Post-change full gate set (format, lint, full vitest, build, knip) | see `FINAL-DELIVERY-REPORT.md` §test evidence |
| Real-browser verification of each Wave 1/2 fix | placeholder + `.page-title` verified in the running app; full sweep via Playwright |
| Playwright `smoke` + `visual` on an isolated harness (own API on `:8100`, own web on `:5273`, own seeded temp DB) | running; results in `VISUAL-QA-REPORT.md` |
| Accessibility sweep (browser axe) | see `ACCESSIBILITY-REPORT.md` |
| Performance lab measurement | see `PERFORMANCE-REPORT.md` |
| Independent review | see `REGRESSION-AND-INDEPENDENT-REVIEW.md` |

### Why the harness needed isolating

The first `playwright test` run **failed 2/2 smoke tests** with "Email or password is
incorrect." Root cause, established from evidence rather than guessed: the harness defaults
to `reuseExistingServer: true` outside CI, so it adopted the already-running dev API on
`127.0.0.1:8000` and **skipped its own seeding**. That API answers `/health` correctly but is
serving a different SQLite file from the one `make seed` writes. (My seed did work:
`apps/api/dev.db` now holds all seven `@e2e.test` accounts, `total=31`.)

This was an **environment/targeting problem, not a product regression** — the two failures
touched none of the code changed by this renovation. Fixed by running the harness
self-contained: `CI=1 E2E_API_PORT=8100 E2E_WEB_PORT=5273`, which forces Playwright to start
and seed its own API and web server and leaves the owner's running services untouched.

## Wave 5 — Mobile / Capacitor (NOT DONE, blocked by design)

`AGENTS.md` §13: no `java`, `gradle` or `adb` on this machine, so no Android build, emulator
or device run is possible. The `mobile-chromium` Playwright project (Pixel 5, 393×851) is
the only mobile signal available and **must not be reported as native verification**.

## Rollback

Git is the rollback path and it is complete and reviewable:

1. `git stash list` — clean; nothing stashed.
2. All changes are uncommitted working-tree edits plus new files under
   `apps/web/src/test/cssTokens.ts` and `docs/frontend-renovation/`.
3. To discard everything: `git checkout -- apps/web/src` and delete the untracked additions.
4. To keep the documentation but revert product code only, the exact product files touched
   are: `apps/web/src/styles.css`, `apps/web/src/i18n.ts`,
   `apps/web/src/components/admin/SchoolsCard.tsx`,
   `apps/web/src/components/OfflineLibrary.tsx`,
   `apps/web/src/components/teacher/QPaperReviewPanel.tsx`,
   `apps/web/src/pages/LoginPage.tsx`, plus six files under `apps/web/src/test/`.
5. No migration, no schema change, no dependency change, no lockfile change, no
   configuration change, so there is no data-side rollback to perform.
