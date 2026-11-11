# Component Inventory — Bangla GPT frontend

Inventory of shared primitives and the duplication recorded against them. Compiled from
`apps/web/src/components/`, `AppShell.tsx` and the 22 page modules. Nothing here proposes a
new component: `AGENTS.md` §16 says reuse before adding, and the master prompt §7.6 says do
not refactor a sound component merely to match a library preference.

**Renovation impact: one component changed** — `components/OfflineLibrary.tsx` gained a
failure message (R-06). Everything else in this file is unchanged, and the duplication below
is recorded for the deferred consolidation wave, not fixed.

---

## 1. Shared primitives — `src/components/ui.tsx`

| Component | Signature highlights | Variants / states | A11y contract | Ref |
|---|---|---|---|---|
| `Button` | `variant`, `size`, `block`, `loading`, extends `ButtonHTMLAttributes` | primary / teal / ghost / soft / danger / default; sm / md / lg; `loading` → `aria-busy` | native `<button>`; **defaults `type="button"`** (so it cannot accidentally submit an ancestor form — relied on by the R-12 fix) | 20-61 |
| `Card` | `title`, `action`, spreads `rest` | — | `rest` passes `role` / `aria-*` through to the DOM, so callers can make it a region | 63-92 |
| `Badge` | `tone` | 5 tones | colour is never the only channel — each badge carries text | 94-114 |
| `Spinner` | `label?` | — | decorative by default | 116-124 |
| `ProgressRing` | `value`, `label` | — | `role="img"` + Bangla-aware `aria-label`; **renovation touched its CSS track only (R-05)**, not the component | 126-159 |
| `Stat` | `value`, `label` | — | — | 161-168 |
| `LoadError` | `message?`, `onRetry?`, `className?` | with/without retry | `role="alert"`; the product's standard honest-failure surface — 19 call sites. **Reused by R-03** rather than inventing a new error UI | 183-204 |
| `Modal` | portal, focus trap, Esc, scroll lock, focus restore | — | full dialog contract | 208-327 |
| `Skeleton` | `w`, `variant` | 4 variants | `aria-hidden`; geometry-stable | 330-356 |
| `Field` | `label`, `hint`, `error` | — | injects `aria-describedby` / `aria-invalid` | 368-420 |
| `Segmented` | `options`, `value`, `onChange` | — | `role="group"` + `aria-pressed`; **deliberately not a tablist** | 431-459 |
| `Avatar` | `name`, `size`, `tone` | 4 sizes × 3 tones | accessible-name from `name` | 462-484 |
| `TrendMark` | `delta` | up/down/flat | — | 492-524 |

## 2. Domain components

| File | Responsibility | Notes |
|---|---|---|
| `components/AppShell.tsx` | shell: 3 variants (`has-sidebar` staff / `shell-student` / bare), topbar action cluster, student bottom nav, staff sidebar, offline banner, impersonation banner | 5 navigable destinations per student and per teacher role |
| `components/SearchBox.tsx` | global search combobox (students only) | debounced 300 ms; full keyboard contract; href allowlist via `uiPathOf` |
| `components/NotificationBell.tsx` | notification menu + 60 s poll while visible | stops on `visibilitychange`; menu keyboard contract |
| `components/OfflineLibrary.tsx` | **CHANGED (R-06)** — list and free offline chapter copies | now reports a failed delete; previously silent |
| `components/ParentInviteCard.tsx` | guardian invite codes: generate, list, revoke | revoke has no confirmation (**R-13**) |
| `components/ActivityHeatmap.tsx` | activity streak heatmap | labelled image; colour + `title` + visually-hidden text |
| `components/QuizOptionGroup.tsx` | shared radio group for every quiz surface | roving tabindex, Arrow/Home/End |
| `components/VoiceButton.tsx` | Web Speech bn-BD input | hidden when unsupported; `aria-pressed` while listening |
| `components/ConversationChip.tsx` | one tutor conversation row | Enter/Escape/blur rename commit |
| `components/ConsentReconfirmNotice.tsx` | consent re-confirmation banner | explicit accept, never a silent flag clear |
| `components/SkipLink.tsx` | skip to `#main-content` | present on public routes too |
| `components/UpdateBanner.tsx` | new-version banner | never auto-reloads |
| `components/AppErrorBoundary.tsx` | route-level error boundary | keeps nav alive; clears on navigation |
| `components/BrandMark.tsx`, `PublicLanguageToggle.tsx` | identity + public language switch | |
| `components/admin/*` | `AiQualityCard`, `FeedbackQueueCard`, `RefusalAuditCard`, `SchoolsCard` (**CHANGED, R-03**), `VersionsCard` | each owns its query and handlers; page passes `onChanged`/`onError` |
| `components/school/SchoolSections.tsx` | 5 independent school sections | per-section loading / error+retry |
| `components/teacher/CreateHub.tsx` | worksheet / answer-key / homework / rubric generation, job polling, document library | polls every 2.5 s only while a job is in flight |
| `components/teacher/QPaperReviewPanel.tsx` | **CHANGED (R-11)** — QP stepper, validation checklist, per-question review/edit, PDF export | per-question label corrected from the bulk one |
| `components/teacher/ShortTestRow.tsx` | one short-test row | |

## 3. Recorded duplication — the honest part

| # | Duplication | Evidence | Consequence |
|---|---|---|---|
| 1 | **Two button vocabularies.** `ui.tsx` emits `.btn .btn-*`; a legacy `button.primary` / `button.secondary` / `button.small` set lives at `styles.css:3076-3112` with no owner in `ui.tsx`. | 7 raw call sites: `AppShell.tsx:92`, `ForgotResetPage.tsx:89,124,179`, `ParentDashboard.tsx:149`, `AdminDashboard.tsx:153,163` | Two vocabularies for one primitive; `formControlBoundary.test.ts` asserts `button.secondary` as a live selector, so retiring it means rewriting an a11y guard in the same change — deferred, Wave 3.1 |
| 2 | **Three parallel stat layouts** — `.stat` (1135), `.stat-row > div` (3141), `.landing-stats > div` (4735) — same information shape, three fills, three inner-class conventions (`.stat-value/.stat-label` vs `.num/.lbl` vs bare `<strong>/<span>`) | **86** raw `className="stat…"` sites against **5** `<Stat>` uses | Highest-churn change in the repo; overlaps the same legacy layer as #1; would invalidate most visual baselines at once — deferred, Wave 3.2 |
| 3 | `.card` declared twice | `styles.css:719` and `4349` | The later wins; the earlier is dead weight that makes intent unreadable. Recorded, not removed — the two are *not* byte-identical, so removing the first needs a consumer audit |
| 4 | `.hero` declared twice (19 `.hero` selectors total) | `styles.css:1624`, `4102` | Same |
| 5 | `.ring` declared twice | `styles.css:1202`, `4370` | The later wins entirely; **R-05 fixed its track** in the winning rule |
| 6 | `.input` matched by 12 rules, `.chip` by 10, `.btn` by 24 | grep on selector counts | Stacked overrides make the effective style hard to reason about |
| 7 | Class-redeclaration as a proxy: `.hero` 19, `.quick-tile` 15, `.bnav-item` 13, `.sidebar` 10 | grep | Same |

## 4. What this means for the next wave

Items 1–2 are the real debt, and they are blocked on each other: both live in the same legacy
compat layer (`styles.css:3054-3112`), and both are gated by an existing accessibility
assertion. Doing them properly means one component-migration wave with the full 60-snapshot
visual review cycle behind it — which is why they were deferred rather than attempted at the
edge of this delivery (`IMPLEMENTATION-PLAN.md` Wave 3).

Nothing in the current delivery makes that wave harder: no new component was added, no new
class vocabulary introduced, and the one new CSS addition (the global `::placeholder` rule)
is a single global rule over a token, not a new pattern.
