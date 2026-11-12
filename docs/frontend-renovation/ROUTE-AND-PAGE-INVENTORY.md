# Route and Page Inventory — Bangla GPT web

Captured: 2026-11-11 · HEAD `03dfe21` · source of truth: `apps/web/src/App.tsx`
(re-read directly; every row cites the declaration line).

Scope note: this file inventories **client-side routes**. The API route baseline is a
separate, pre-existing artifact at `docs/route_baseline.md` (144 method+path routes,
captured 2026-10-30) and is **not** duplicated here.

---

## 1. Route gate model

One guard component, `RequireAuth` (`App.tsx:84-119`), wraps every authenticated route.
Its decision order is the security-relevant contract and must not be reordered:

| Order | Condition | Behaviour | Line |
|---:|---|---|---|
| 1 | `!getToken()` | `<Navigate to="/login" replace />` | `App.tsx:92` |
| 2 | `loading` | polite loading region + skeletons (shell NOT rendered) | `App.tsx:93-102` |
| 3 | `apiUnreachable` | `ApiUnreachable` screen — **keeps the token**, offers retry | `App.tsx:106` |
| 4 | `me === null` | `<Navigate to="/login" replace />` (session genuinely refused) | `App.tsx:109` |
| 5 | `role && me.role !== role` | `<Navigate to={ROLE_HOME[me.role] ?? "/login"} replace />` | `App.tsx:110-111` |
| 6 | otherwise | `<AppShell><RouteErrorBoundary>{children}</RouteErrorBoundary></AppShell>` | `App.tsx:114-118` |

Step 3 before step 4 is deliberate (comment `F-107`): a dead backend must not look to a
child like their account was closed. Any renovation of the loading/error shell must keep
that distinction.

Public routes render **outside** `AppShell` and get their own `SkipLink` +
`PublicLanguageToggle` at `App.tsx:192-193` (`I18N-12`, `A11Y-02`).

---

## 2. Public routes (no shell, no auth)

| # | Path | Component | Gating | Launched at | Notes |
|---:|---|---|---|---|---|
| 1 | `/` | — | redirect | — | → `ROLE_HOME[me.role]`, else `/welcome` (`App.tsx:184,195`) |
| 2 | `/welcome` | `pages/WelcomePage.tsx` | anonymous only; authed → role home | `App.tsx:208-207` | `RouteErrorBoundary` wrapped |
| 3 | `/login` | `pages/LoginPage.tsx` | anonymous only; authed → `?next` or home | `App.tsx:228-227` | `safeNextPath` open-redirect guard |
| 4 | `/register` | `pages/RegisterPage.tsx` | anonymous only | `App.tsx:240-239` | |
| 5 | `/forgot` | `pages/ForgotResetPage.tsx` | any | `App.tsx:248-247` | reset **and** verify tabs |
| 6 | `/privacy` | `pages/LegalPage.tsx` (`kind="privacy"`) | any | `App.tsx:256-255` | |
| 7 | `/terms` | `pages/LegalPage.tsx` (`kind="terms"`) | any | `App.tsx:264-263` | |
| 8 | `/status` | `pages/StatusPage.tsx` | any | `App.tsx:272-271` | |
| 9 | `/maintenance` | `pages/MaintenancePage.tsx` | any | `App.tsx:280-279` | deployment rewrite target (`UX-06`) |

## 3. Student routes — `role="student"`

| # | Path | Component | Declared |
|---:|---|---|---|
| 10 | `/student` | `pages/student/HomePage.tsx` | `App.tsx:290-289` |
| 11 | `/student/learn` | `pages/student/LearnPage.tsx` → `LearnPage` | `App.tsx:298-297` |
| 12 | `/student/learn/:subject/:chapter` | same module → `LearnChapterPage` | `App.tsx:306-305` |
| 13 | `/student/tutor` | `pages/student/AITutorPage.tsx` | `App.tsx:314-313` |
| 14 | `/student/quiz` | `pages/student/QuizPage.tsx` | `App.tsx:322-321` |
| 15 | `/student/me` | `pages/student/MePage.tsx` | `App.tsx:330-329` |

Deep-link / query contract carried by these routes (preserve exactly):
`/student/quiz?count=` , `?subject=` , `?result=1`; `/student/learn/:subject/:chapter?class=`;
`/student/tutor` reached with router `state` = `{ ask }` | `{ explain, backToResult }`
(`useTutorHandoff.ts`).

## 4. Teacher routes — `role="teacher"`

| # | Path | Component | Declared |
|---:|---|---|---|
| 16 | `/teacher` | `pages/teacher/TeacherHomePage.tsx` | `App.tsx:340-339` |
| 17 | `/teacher/create` | `pages/teacher/CreatePage.tsx` | `App.tsx:348-347` |
| 18 | `/teacher/classes` | `pages/teacher/ClassesPage.tsx` | `App.tsx:356-355` |
| 19 | `/teacher/assessments` | `pages/teacher/AssessmentsPage.tsx` | `App.tsx:364-363` |
| 20 | `/teacher/analytics` | `pages/teacher/AnalyticsPage.tsx` | `App.tsx:372-371` |
| 21 | `/teacher/profile` | `pages/teacher/TeacherProfilePage.tsx` | `App.tsx:380-379` |

Query contract: `/teacher/create?kind=`, `/teacher/assessments?tab=`.

## 5. Parent / admin / school routes

| # | Path | Component | Role gate | Declared |
|---:|---|---|---|---|
| 22 | `/parent` | `pages/ParentDashboard.tsx` | `parent` | `App.tsx:388-387` |
| 23 | `/admin` | `pages/AdminDashboard.tsx` | `admin` | `App.tsx:396-395` |
| 24 | `/school` | `pages/SchoolDashboard.tsx` | `school_admin` | `App.tsx:404-403` |

**Confirmed discrepancy (recorded, not "fixed"):** `pages/SchoolDashboard.tsx:9` documents
itself as serving "school_admin / admin", but the route gate is `role="school_admin"` only.
A pure `admin` account is redirected to `/admin`. Whether a platform admin *should* see
`/school` is a product decision — out of renovation scope, preserved as-is, flagged for
owner review (see RISK-REGISTER `R-14`).

## 6. Fallback

| # | Path | Component | Behaviour |
|---:|---|---|---|
| 25 | `*` | `pages/NotFoundPage.tsx` | wrapped in `RouteErrorBoundary` (`App.tsx:406-410`) |

## 7. Shell-level affordances (present on every authenticated route)

Not routes, but navigable surfaces that must survive any shell renovation:

- Bottom navigation, 5 student destinations (`AppShell.tsx:36-42,262-278`).
- Staff sidebar — teacher 5 items (`AppShell.tsx:46-62`), other staff dashboard+status
  (`AppShell.tsx:234-254`).
- Topbar cluster: global search (students), PWA install, notification bell, teacher profile,
  language toggle, theme toggle, sign out (`AppShell.tsx:149-212`).
- Footer: Privacy · Terms · Status (`App.tsx:491-504`).
- Banners: offline (`AppShell.tsx:64-82`), impersonation (`AppShell.tsx:84-104`),
  new-version (`UpdateBanner.tsx`).

## 8. Responsive archetype per route family

Assigned from the actual layout code, used later to pick which viewports get full
coverage versus smoke-only (master-prompt §7.5 coverage rule).

| Archetype | Routes | Why |
|---|---|---|
| Marketing / public hero | 2, 3, 4, 5 | full-bleed hero + card, no shell |
| Long-form document | 6, 7 | reading measure dominates |
| Single status card | 8, 9 | one card, no shell |
| Student dashboard | 10, 15 | card stack + stat ring + bottom nav |
| Student reader (3-pane workspace) | 11, 12 | tablist workspace, largest reflow risk |
| Streaming conversation | 13 | pinned composer, keyboard-critical |
| Quiz runner | 14 | single-question focus + pager |
| Teacher data surface | 16, 17, 18, 19, 20, 21 | tables, matrices, forms, print |
| Parent report | 22 | child tables + segmented periods |
| Admin console | 23 | paginated table + destructive actions |
| School overview | 24 | five independent sections + tables |

## 9. Coverage denominator

- **Accessible routes** (reachable by some role in a normal session): **25 declared route
  entries**, of which 1 is a redirect (`/`) and 1 is a catch-all (`*`) → **23 addressable
  pages**.
- Route smoke tests are organised as prefixes: `/student` covers two paths, `/student/learn`
  covers three, so the Playwright crawler (`e2e/crawl.spec.ts`, 7 tests) plus the axe sweep
  (24 tests) already provide partial smoke coverage. Post-renovation per-route smoke status
  is recorded in `FEATURE-PARITY-REPORT.md`.

No route was found that is unreachable from navigation, and no navigation entry was found
that points at a missing route (checked against `STUDENT_NAV`/`TEACHER_NAV`/staff sidebar
and the `Link`/`navigate` calls across `src/`).
