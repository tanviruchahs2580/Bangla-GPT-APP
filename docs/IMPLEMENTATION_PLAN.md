# BANGLA GPT — UI/UX UPGRADE · PHASE 2 IMPLEMENTATION PLAN

> Master prompt: `Bangla-GPT-UI-UX-Upgrade-Master-Prompt.md` · Branch:
> `feature/ui-ux-blueprint-upgrade-20260830`
> This is a **plan only — no code changed**. Awaiting approval before Phase 3 (implementation).

---

## 1. STRATEGY OVERVIEW

- **Framework reality:** the app is a **responsive React web app** (Vite + react-router v7), not
  React Native. The blueprint's "mobile" target is delivered via **mobile-first responsive web +
  PWA install**, not native tab bars.
- **Approach:** progressive enhancement over the existing working backend/contract. **Do not break**
  auth, data models, or API contracts (constraint #4). Add an app shell + design system + new
  screens **incrementally**; the current working dashboards remain as a fallback during migration.
- **Learning-Journey-First** UI: onboarding → setup → Home (AI entry first) → AI Tutor → Learn →
  Quiz → Progress. Calm/Clear/Trusted/Friendly/Intelligent.
- **Dependencies to add** (subject to approval):
  - `@tanstack/react-query` — data layer (kills silent-catch debt)
  - `react-markdown` + `remark-math` + `katex` — structured/math answers
  - `lucide-react` — SVG icon system (replace emoji)
  - `recharts` — progress charts (lightweight, optional P1)
- **Backend untouched** in this phase plan except reading existing endpoints for the data layer.

---

## 2. OPEN DECISIONS (need your confirmation — marked 🔵)

| # | Decision | Default recommendation |
|---|---|---|
| D1 🔵 | Visual direction | **Indigo/blue primary** per blueprint (teal secondary, calm neutrals); keep dark mode. *Alternative: keep current green.* |
| D2 🔵 | Scope cadence | **P0 fully first** (design system → shell → Home → AI → Learn → Quiz/Progress), then P1 in a 2nd approved batch. |
| D3 🔵 | Bottom nav labels/lang | Bangla-first: **হোম · শেখা · এআই · কুইজ · আমি** with EN secondary. |
| D4 🔵 | Old dashboards | Keep as `/debug` fallback during migration, then deprecate; teacher/parent/admin = P2 keep v1 dashboards (styled only). |

---

## 3. ARCHITECTURE CHANGES

```
apps/web/src/
  main.tsx                    # keep; add QueryClientProvider, updated route tree
  AppShell.tsx  (NEW)         # top bar + bottom nav + <Outlet/>
  routes.tsx    (NEW)         # nested tab routes + deep links
  styles/
    tokens.css  (NEW)         # design tokens (color/type/spacing/motion/radius)
    base.css    (NEW)         # reset/base
    globals.css (EXTENDED)    # move existing styles → co-located modules
  components/
    ui/         (NEW)         # Button, Input, Card, Badge, ProgressBar, Skeleton,
                              # EmptyState, ErrorState, Toast, Modal, BottomSheet, Tooltip
    layout/     (NEW)         # AppShell, BottomNav, TopBar
    tutor/      (NEW)         # AiAnswer (A–E), QuickActions, SourceCard, TypingIndicator
  data/         (NEW)         # react-query hooks (useMe, useProgress, useConversations, …)
  pages/        (EXPANDED)    # + Splash, Onboarding, StudentSetup, Home, Tutor, Learn,
                              # SubjectDetail, Chapter, Concept, QuizHub, Practice, Result,
                              # Revision, Exam, Search, Profile, Settings
  i18n.ts  (EXTENDED)         # + ~150 keys, document lang sync fix
```

---

## 4. PHASE 3 — DESIGN SYSTEM FOUNDATION (do first)

| Task | Files/components | Tokens | Risk | Complexity |
|---|---|---|---|---|
| 3.1 Color system | `styles/tokens.css` | Indigo/blue primary scale, teal secondary, success/warn/error, surface tiers, text tiers, focus ring | Low | S |
| 3.2 Typography | `styles/tokens.css`, `main.tsx` | Display, H1–H3, Body-L, Body, Caption; Noto/Hind Bengali + Inter; math-ready | Low | S |
| 3.3 Spacing | `styles/tokens.css` | 4/8/12/16/24/32/48/64 | Low | S |
| 3.4 Core component lib | `components/ui/*` | Button, Input, Select, Card, Badge, ProgressBar, Skeleton, EmptyState, ErrorState, Toast, Modal, BottomSheet, Tooltip, SegmentedControl | Medium | M (first pass) |
| 3.5 Icons | `@lucide-react` + `<Icon>` wrapper | currentColor, stroke 1.75 | Low | S |
| 3.6 Motion | motion stories in CSS/util | 150–350 ms, easings, reduced-motion respected | Low | S |
| 3.7 Dark + High-Contrast | tokens + base | `[data-theme]`, `[data-contrast=high]`, prefers-dark | Medium | M |

**Done-when:** a `<Story>`-style `tokens.css` smoke page renders every primitive; axe-clean on primitives.

---

## 5. PHASE 4 — CORE SCREENS (incremental, P0)

### 5.1 Splash + Onboarding + Student Setup
| Item | Components | Impact | Risk | Cx |
|---|---|---|---|---|
| Splash | `pages/Splash.tsx`, AppShell route | `main.tsx` routes | Low | S |
| Onboarding (3-screen) | `pages/Onboarding.tsx`, `OnboardingStep`, progress dots | new route; store intent | Medium | M |
| Student Setup | `pages/StudentSetup.tsx` (class→group→goal) | registration already captures class; add goal; API ok | Medium | M |

**API:** class/goal are user-editable via `/users/me` PATCH (backed). Setup persists goal to profile (add optional column later if needed — flagged).

### 5.2 App Shell + Home Dashboard (highest priority)
| Item | Components | Impact | Risk | Cx |
|---|---|---|---|---|
| AppShell + BottomNav | `layout/AppShell.tsx`, `layout/BottomNav.tsx` | `main.tsx` route tree wraps authed screens | Medium | M |
| Home | `pages/Home.tsx` | greeting + class selector; **AI entry (top)**; Continue Learning; আজকের plan; weak topics; my subjects (horizontal scroll) | Medium | H |

**Home data:** resolve via `useMe`, `useProgress`, `useConversations` (react-query). Weak topics come from existing `/students/{id}/progress`.

### 5.3 AI Tutor Workspace
| Item | Components | Impact | Risk | Cx |
|---|---|---|---|---|
| Structured answer | `tutor/AiAnswer.tsx` + react-markdown+KaTeX | reuse `postStream` SSE | Medium | H |
| Quick actions | `tutor/QuickActions.tsx` (context-aware chips) | heuristic from topic/subject | Medium | M |
| Source cards | `tutor/SourceCard.tsx` (tap→expand) | reuse sources from done-event | Low | S |
| Understanding Check | `tutor/UnderstandingCheck.tsx` (inline MCQ) | reuse quiz engine | Medium | M |
| Edge/loading states | `tutor/TutorStates.tsx` (searching/no-answer/network) | map ApiError codes | Medium | M |

**AI answer structure (blueprint):** Short Summary → Step-by-step Explanation → Example → Visual(if needed) → Understanding Check + Quick Actions + Sources.

### 5.4 Learn Flow (Subjects → Chapter → Concept)
| Item | Components | Impact | Risk | Cx |
|---|---|---|---|---|
| Subjects | `pages/Learn.tsx` (+filters) | new | Medium | M |
| Subject Detail | `pages/SubjectDetail.tsx` (progress + chapters) | new | Medium | M |
| Chapter Overview / Path | `pages/Chapter.tsx` (Concept→Examples→Practice→Quiz→Revision stepper) | new | Medium | M |
| Concept Learning | `pages/Concept.tsx` (structured reader) | new; content = corpus present via API | Medium | M |

**Content source:** structured concept pages derive from the grounded corpus endpoint; illustrative content kept minimal & grounded (constraint #3).

### 5.5 Practice & Quiz (existing engine, new UI)
| Item | Components | Impact | Risk | Cx |
|---|---|---|---|---|
| Quiz Hub | `pages/QuizHub.tsx` | wrap existing `/quizzes` | Low | S |
| Quiz Screen | `pages/QuizScreen.tsx` (timer optional) | existing submit flow | Medium | M |
| Practice Mode | `pages/Practice.tsx` (Easy/Med/Challenge + AI-recommend) | reuse quiz; add difficulty param (must be API-optional — flag) | Medium | M |
| Result | `pages/QuizResult.tsx` (strength/weak + next actions) | existing `/quizzes/{id}/submit` | Medium | M |

### 5.6 Supporting P0 screens
Search, Progress/Analytics (charts), Profile, Settings (low-data toggle) — see §6.

---

## 6. PHASE 5 — CROSS-CUTTING (P0 essentials + P1)

| Concern | Work | Priority |
|---|---|---|
| **Low Data Mode** | Setting + reduced images/animations, smaller bundles, compression flag sent to API | P1 (mandatory) |
| **Offline cache** | Workbox SW: cache app shell + downloaded chapters; queue actions | P1 |
| **Math rendering** | react-markdown + KaTeX in AiAnswer | P0 |
| **Accessibility** | fix `<html lang>`, modal focus trap, contrast ≥4.5, axe in CI | P0 |
| **Data layer** | react-query: kill silent catches, add retry/error/empty/loading everywhere | P0 |
| **Error boundaries** | global boundary per route | P0 |
| **Performance** | route lazy-loading (`React.lazy`) | P0 |

---

## 7. TESTING & QUALITY PLAN (cross-phase)

- **Unit/component:** vitest + RTL per new component.
- **A11y:** `jest-axe` on every screen (CI gate ≥0 violations).
- **E2E:** add **Playwright** (register→onboard→home→ask→quiz→progress; parent link; purge). CI bolt-on.
- **Visual regression:** Playwright screenshot baseline for Home/AI/Learn/Quiz.
- **Perf/lighthouse:** budget on CI (load < 200KB gzip, a11y ≥95, perf ≥85).

---

## 8. MILESTONES & SEQUENCING

| Milestone | Content | Depends on | Approval gate |
|---|---|---|---|
| M1 | Design tokens + core components + icons + motion | — | ✅ this approval |
| M2 | App Shell + bottom nav + Splash + Home | M1 | per-milestone |
| M3 | AI Tutor workspace + math + sources + checks | M2 | per-milestone |
| M4 | Learn flow (Subjects→Chapter→Concept) | M2 | per-milestone |
| M5 | Quiz Hub/Practice/Result + Progress charts | M2,M4 | per-milestone |
| M6 | P1: search, low-data, offline, revision, exam, voice/image | M3–M5 | separate batch |

**Per master prompt:** each milestone delivers a preview + screenshot + summary and stops for your
approval before the next. No git push/commit/deploy without your explicit go.

---

## 9. RISK LOG

| Risk | Mitigation |
|---|---|
| Large scope (many new screens) | Milestoned P0-first; reuse existing engines (quiz/stream/progress) |
| Breaking auth/contract | Constraint #4; data layer only reads existing endpoints; backend untouched in M1–M3 |
| Math/content accuracy | Grounded-only; no hallucinated NCTB content |
| Low-end perf | lazy routes, low-data flag, reduced animations |
| Emoji→icon regressions | lucide wrapper + visual baseline |

---

## 10. IMMEDIATE NEXT EXECUTION (if approved)

Start **Milestone 1 — Phase 3 foundation**:
1. Add deps (`@tanstack/react-query`, `react-markdown`, `remark-math`, `katex`, `lucide-react`).
2. Create `styles/tokens.css` + `base.css` (indigo palette unless you override D1).
3. Build core `components/ui/*` primitives.
4. Fix `<html lang>` + silent-catch debt as part of M2 data layer.
5. Run vitest/tsc/build + axe; produce preview + screenshots.

Confirm **D1 (indigo vs green)** and **D2 (P0-first cadence)** to lock the plan, and I'll begin M1.
