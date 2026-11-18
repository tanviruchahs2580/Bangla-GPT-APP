# TABLE_INVENTORY — data-table surfaces and migration decisions

**Date:** 2026-11-18 · Branch `feat/mobile-platform-hardening`
**Method:** exhaustive source search for `<table`/`<thead`/`.table-wrap`/`.data`/`.cardable`
and map/list implementations that behave like tables, against current HEAD.

Shared CSS contract (unchanged by this workstream): `.table-wrap` (scroll bounder),
`table.data` (elevated table), `.cardable` (≤760 px labelled-card fallback via
`data-label`), `.cell-wrap`/`.cell-wrap-sm` (long-value wrapping).

## Decision legend

- **MIGRATED** — now renders through `components/ResponsiveTable.tsx`; behaviour preserved.
- **RETAINED (exception)** — stays bespoke; documented reason.

## Inventory

| # | Surface (file) | Route / role | Columns & behaviour that had to survive | Decision |
|---|---|---|---|---|
| A1 | `AdminDashboard.tsx` users table | /admin | id/email/role, role `<select>` + impersonate (hidden for admin/school_admin), cardable, `cell-wrap-sm` email, pagination outside | **MIGRATED** (cardable) |
| A2 | `admin/SchoolsCard.tsx` schools | /admin | name button (toggles invites), counts, invite role select + create | **MIGRATED** |
| A3 | `admin/SchoolsCard.tsx` invites | /admin | caption, inline `colSpan` LoadError row (exclusive with data rows), conditional revoke action | **MIGRATED** (`tbodyPrefix`, `rows={failed ? [] : …}`) |
| A4 | `admin/FeedbackQueueCard.tsx` queue | /admin | rating glyph ±/−/·, comment+note `cell-wrap`, triage note input + toggle button | **MIGRATED** |
| A5 | `admin/VersionsCard.tsx` versions | /admin | composite row key `subject-class-chapter`, version totals, wrapped cells | **MIGRATED** |
| A6 | `admin/RefusalAuditCard.tsx` refusals by reason | /admin | reason label + count over `Object.entries` | **MIGRATED** |
| A7 | `ParentDashboard.tsx` children | /parent | Latin-digit student id (numeral policy), honest-null average, progress button with empty `data-label` | **MIGRATED** (cardable) |
| A8 | `ParentDashboard.tsx` per-chapter | /parent (child selected) | asked/correct/accuracy, weak badge < 60% | **MIGRATED** (cardable) |
| A9 | `SchoolDashboard.tsx` at-risk | /school | honest-null average badge (FE-FIX-006 comment preserved), trend | **MIGRATED** |
| A10 | `school/SchoolSections.tsx` students | /school | name/class/quizzes/last-active (`muted` cell class) | **MIGRATED** |
| A11 | `school/SchoolSections.tsx` teachers | /school | subjects join or "—" | **MIGRATED** |
| A12 | `school/SchoolSections.tsx` classrooms | /school | graded/attempts fraction, honest-null average | **MIGRATED** |
| A13 | `school/SchoolSections.tsx` coverage | /school | uncovered-subject warn badges, read/available fraction | **MIGRATED** |
| A14 | `teacher/ClassesPage.tsx` roster | /teacher/classes | health dot + visually-hidden label, invite-pending badge, detail action | **MIGRATED** |
| A15 | `teacher/ClassesPage.tsx` CSV import result | /teacher/classes | **no `<thead>`** — renders error/warning/success rows only | **RETAINED** — a header-less result list is not a data table; forcing headers would invent content |
| A16 | `teacher/AssessmentsPage.tsx` roster + select | /teacher/assessments | select-all checkbox in the header (component accepts node headers), per-row checkbox, assign action with active variant | **MIGRATED** |
| A17 | `teacher/AssessmentsPage.tsx` attempt results | /teacher/assessments | status badges, honest-null score; **gap fixed:** header-only table when empty → now `emptyMessage={t("noResults")}` (existing key, bn+en) | **MIGRATED** |
| A18 | `teacher/AnalyticsPage.tsx` weak-concept matrix | /teacher/analytics | dynamic per-student columns, per-cell heat class + `title` tooltip, `th scope="row"`, summary row | **RETAINED** — a per-cell-styled matrix, not a record table; forcing it into the component would require arbitrary per-cell class/attr hooks (over-generalisation per D2) |
| A19 | `teacher/AnalyticsPage.tsx` curriculum coverage matrix | /teacher/analytics | dynamic per-subject columns, `th scope="row"`, badge cells | **MIGRATED** (`rowHeader` support added for this + future matrices) |
| A20 | `teacher/CreateHub.tsx` import-jobs list | /teacher/create | **no `<thead>`**, status-line rows | **RETAINED** — same reason as A15 |
| — | `teacher/CreateHub.tsx` document library | /teacher/create | uses `.table-wrap`/`.data` classes but renders a card/list, not tabular records | **RETAINED** — list by design (D1: do not force lists into grids) |

**Tally: 17 migrated, 3 retained (+1 list misusing table classes).**

## Component contract (`components/ResponsiveTable.tsx`)

- Generic `TableColumn<T>`: stable `id`, localized `header` (any node — A16's select-all
  checkbox), `cell(row)`, optional `cellClassName`, optional `mobileLabel` (defaults to a
  string header).
- `rowKey(row, index)` — string keys (numeric ids stringified at call sites).
- `caption`, `actions(row)` + `actionsMobileLabel` (trailing column, empty `th` as before),
  `cardable`, `emptyMessage` (opt-in, keeps empty distinct from loading/error),
  `tbodyPrefix`/`tbodySuffix` (documented escape hatches: A3's inline error row, matrix
  summary rows), `rowHeader` (first column as `th scope="row"`).
- **Not in the component** (page-owned, behaviour preserved): fetching, loading/error/empty
  composition, pagination, filtering, authorization. No sort support — no migrated surface
  sorts; add with a real consumer, not speculatively.

## Verification

- Component unit tests: `src/test/responsiveTable.test.tsx` (7 tests — wrapper/headers/
  keys, data-label gating, caption/actions, empty row, escape hatches).
- Governance tests updated to the new contract, intent unchanged:
  `e3TableGuard.test.ts` (cardable adoption now checks the component + `cardable` prop and
  still pins the component's emitted `data-label`/`"data"`/cardable contract) and
  `pageSizeRatchet.test.ts` (two recorded raises with dated justification comments —
  AssessmentsPage 636→638, ClassesPage 692→702; the declarative column objects cost a few
  page lines while the replaced markup is now shared).
- Full web suite green after migration; prettier clean; tsc/eslint clean.
- Mobile/desktop visual checks run in the Phase 6 integrated matrix (320–430 px card
  fallback, desktop table) — device-matrix rows shared with DEVICE_VERIFICATION_VC206.md.
