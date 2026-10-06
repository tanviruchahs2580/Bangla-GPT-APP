# PROJECT REVIEW & PRODUCTION-GRADE ROADMAP — Bangla GPT APP

> Author: Enterprise full-stack review (frontend/UX focus + backend context)
> Baseline: validation report v0.3.1 (verdict B) + direct code reading of `apps/web/src`
> Goal of this doc: restate the product reality, assess current stage, enumerate problems a
> developer and an end-user hit today, audit UI/UX/frontend quality parameter-by-parameter,
> then give a *complete, ordered* set of steps to reach an international-level, production-grade
> app. Each step has a "what / why / how / done-when".

---

## PART A — PROJECT REALITY (goal / target / focus / scale)

- **Goal:** A safe, NCTB-grounded, Bangla-first AI personal tutor for Bangladesh school students
  (classes 1–12). It answers textbook-anchored questions with citations, runs curriculum quizzes,
  shows progress analytics, and supports teacher/parent/admin roles.
- **Target users:** Primary = Bangla-speaking students (mobile-first, low-end Android). Secondary =
  teachers (roster/assign), parents (consent + child progress), admins (ops). Stakeholders may be
  non-Bangla (hence the EN locale exists).
- **Focus:** Grounding/trust (no hallucinated facts), child safety, and measurable learning outcomes.
- **Scale intent:** National. Realistic pilot = thousands of students; design point = tens of
  thousands concurrent at peak (evening study hours). This drives the "international-level" bar: it
  must feel like a polished consumer edtech app (think Duolingo/Quizlet/Khan Academy level of
  polish), not an internal tool.

---

## PART B — CURRENT STAGE ASSESSMENT

**Backend: strong for a v0.3.** Auth/RBAC/quiz/progress/grounding/moderation/observability all
implemented and tested (157 pytest, ruff/mypy clean). Verdict B is fair.

**Frontend: functional MVP, not yet "international-level".** It has:
- A token-based CSS design system (decent tokens, dark mode, responsive breakpoint).
- i18n (bn/en) with a typed dictionary.
- Core flows wired (chat+SSE, quiz, progress, account delete/export, login/register/reset/verify).
- A11y seeds (aria-live, roles, focus-visible, reduced-motion).

But it is **MV-quality in three dimensions**: (1) no resilient data/error layer, (2) visual identity
is generic, (3) no automated UX/a11y/e2e safety net. It is *usable*, not yet *delightful or
bullet-proof*.

---

## PART C — PROBLEMS FACED TODAY

### C1. As a developer / operator
- Silent failures mask bugs: `loadConversations().catch(() => undefined)` and progress
  `get(...).catch(() => undefined)` swallow errors — a backend outage looks like "empty UI", not
  "error state". Hard to diagnose in prod.
- No frontend error telemetry (Sentry/etc.) — only console errors.
- No e2e or component tests; a CSS refactor can break layouts silently (only 6 vitest, no a11y/e2e).
- Dead/hacky code: `t('askPlaceholder') ? 'টিউটর' : 'টিউটর'` (always 'টিউটর');
  `t('className').replace(/\s*\(.*\)/, '')` in the title — fragile string hacking.
- i18n is incomplete for assistive tech: `<html lang>` stays `"bn"` even after switching to EN
  (see D4).
- Missing production artifacts: `sw.js` is registered in prod but its source may be absent;
  `manifest.webmanifest` is referenced — must exist with icons or installability/PWA fails.

### C2. As an end user (student)
- **Blank screens with no explanation.** If the progress or conversation call fails, the section
  simply doesn't appear. No retry, no "couldn't load" message.
- **No loading state** on first load of progress / conversations — just absent until it pops in.
- **No markdown/math rendering** of tutor answers → a science explanation with formulas/lists is
  shown as a flat blob of text. Weak for an *education* product.
- **No way to stop/regenerate** a streaming answer once sent.
- **Emoji icons** (📘 👍 👎 🙈 👁️) look unpolished and don't localize visually.
- **Language toggle doesn't switch screen-reader language** and there's no obvious language memory
  cue beyond the button.
- **Delete-account modal**: no Escape-to-close, no focus trap, background scroll not locked.
- **No onboarding / empty state** for a first-time student (empty chat + empty progress with no
  guidance).
- Registration has no password-strength meter, no confirm-password, no inline field errors.

### C3. As a teacher / parent / admin
- Teacher dashboard: assigning a quiz has no feedback animation; roster may be empty with only a
  tiny muted line.
- Parent: linking child relies on a code; no step-by-step empty-state guidance.
- Admin: search/purge exist but no bulk actions, no audit log view, no pagination controls visible
  to the eye beyond the table.

---

## PART D — UI/UX & FRONTEND QUALITY AUDIT (parameter by parameter)

| # | Parameter | Status | Notes / Gap |
|---|---|---|---|
| D1 | Visual identity / branding | ⚠️ Weak | Gradient topbar only; no logo/wordmark, no favicon set verified, no illustration system, no empty-state art. |
| D2 | Design system | ⚠️ Basic | Flat CSS with tokens, but no component primitives, no spacing/sizing scale enforcement, no motion tokens, no documented usage. |
| D3 | Color & theme | ✅ OK | Light/dark tokens present; contrast not *measured* (no audit). |
| D4 | i18n correctness | ❌ Bug | `<html lang>` not updated on language switch; EN users get bn lang attribute. |
| D5 | Typography | ✅ OK | Bangla webfonts self-hosted (good); scale exists but not applied uniformly. |
| D6 | Layout / responsive | ✅ OK | 760px breakpoint; chat collapses; mobile conv-list horizontal scroll acceptable but unpolished. |
| D7 | Navigation / IA | ✅ OK | Role-based routes; redirect home; footer legal links. |
| D8 | Loading states | ❌ Missing | No skeletons for progress/conversations; silent absence on error. |
| D9 | Error states / resilience | ❌ Weak | Inline red text only; many fetches swallowed; no retry/empty/error UI. |
| D10 | Forms & validation | ⚠️ Basic | Required/minLength only; no inline field errors, no strength/confirm, email only type-checked. |
| D11 | Feedback / micro-interactions | ⚠️ Basic | Spinner + button states; no toasts, no success animations, no optimistic UI. |
| D12 | Accessibility (a11y) | ⚠️ Partial | aria-live, roles, focus-visible present; missing focus-trap/Escape on modal, lang switch, measured contrast, axe tests. |
| D13 | Icons | ❌ Weak | Emoji icons; not crisp, not themeable, not localizable. |
| D14 | Content rendering | ❌ Weak | Tutor answers plain text; no markdown/KaTeX → poor for math/science. |
| D15 | Performance | ⚠️ OK | No route lazy-loading; fonts self-hosted (good); no bundle analysis in CI. |
| D16 | PWA / offline | ❌ Broken | SW registered but source/strategy likely missing; manifest referenced but unverified; no offline shell. |
| D17 | Testing (frontend) | ❌ Thin | 6 vitest; no component/visual/a11y/e2e; CSS changes unguarded. |
| D18 | Observability (frontend) | ❌ Missing | No error tracking, no privacy-friendly analytics, no funnel/event telemetry. |
| D19 | Security (frontend) | ⚠️ Acceptable | Token in localStorage (XSS surface); acceptable for scope but should note httpOnly-cookie migration path. |
| D20 | Onboarding / empty states | ❌ Missing | No first-run guidance, no illustrations, no tooltips. |

---

## PART E — MISSING STEPS TO PRODUCTION-GRADE (detailed, ordered)

> Phases are dependency-ordered. Backend-gated owner items (NCTB corpus, Gemini paid, domain/TLS/
> SMTP, commit+tag) are listed in Phase 0 for completeness but are **owner actions**, not code steps.

### PHASE 0 — Close the release gate (owner + dev)
- **S0.1 Commit & tag RC `v0.3.1`** (owner approval). Why: traceability. Done-when: `git tag v0.3.1`
  exists, CI green on tag.
- **S0.2 Real NCTB corpus pipeline** (owner/legal). Why: product value. Done-when: classes 1–12
  rights cleared + ingest run; quizzes generate from real chapters.
- **S0.3 Gemini paid tier + key rotation** (owner). Why: free-tier 503s + past key leak. Done-when:
  `GEMINI_API_KEY` in secret store, paid quota, rotate exposed key.
- **S0.4 Domain / TLS / SMTP** (owner). Done-when: HTTPS endpoint + transactional email verified.

### PHASE 1 — Frontend architecture & resilience (do first; unblocks trust)
- **S1.1 Introduce a data layer (TanStack Query or SWR).** What: replace ad-hoc `get(...).then/.catch`
  with hooks (`useProgress`, `useConversations`) that manage loading/error/data + retry + cache.
  Why: kills silent failures (C1/C2/D8/D9). How: add `@tanstack/react-query`, wrap `App` in
  `QueryClientProvider`; rewrite `StudentDashboard` data fetches. Done-when: every list/detail shows
  explicit loading / error / empty / data states; a forced 500 returns a friendly retry UI.
- **S1.2 Global error + toast system.** What: a `<Toaster>` + `useToast()`; map `ApiError.code`
  (rate_limited, network, email_unverified, etc.) to localized copy; surface 429 with backoff hint.
  Why: D9/D11. Done-when: no raw `catch(()=>undefined)` remains in pages; 429 shows "slow down"
  toast; network error shows retry.
- **S1.3 Fix silent-swallow sites.** What: remove `.catch(() => undefined)` in `StudentDashboard`
  (conversations, progress) and replace with query error states. Done-when: grep shows zero
  `catch(() => undefined)` in `src/pages`.
- **S1.4 Abortable streaming + regenerate/stop.** What: pass `AbortController` to `postStream`; add
  Stop button + "Regenerate" on last assistant message. Why: C2. Done-when: user can cancel mid-
  stream; regenerate re-calls with same prompt.

### PHASE 2 — Visual identity & design system (international-level look)
- **S2.1 Define a real design system.** What: extract tokens into a documented scale (space 4–64,
  radii, elevation, type scale, motion 120/200/300ms), add semantic tokens (success/info), add a
  `theme` object in TS for reuse. Why: D2. Done-when: `styles.css` tokens map 1:1 to a `tokens.ts`;
  no magic numbers in components.
- **S2.2 Replace emoji with an SVG icon set.** What: add `lucide-react` (or inline SVG component
  `Icon`), swap 📘👍👎🙈👁️. Why: D13. Done-when: zero emoji in `src`; icons inherit `currentColor`
  and respect dark mode.
- **S2.3 Brand & empty-state illustration system.** What: create a wordmark/logo SVG, favicon set,
  and 3–4 empty-state illustrations (no chats, no progress, no children, no students). Why: D1/D20.
  Done-when: first-run student sees guided empty states, not blank cards.
- **S2.4 Motion & delight.** What: add subtle enter/exit transitions for messages, cards, modal
  (respect `prefers-reduced-motion` already present); success checkmark micro-interaction on quiz
  submit/export. Why: D11. Done-when: transitions defined via motion tokens; reduced-motion verified.
- **S2.5 Markdown + math rendering.** What: render assistant messages with `react-markdown` +
  `remark-math` + `KaTeX` (Bangla + math). Why: D14 (critical for an education product). Done-when:
  a formula/solution renders with proper fractions/lists; citations remain below.

### PHASE 3 — Accessibility & i18n correctness (must-pass for international)
- **S3.1 Fix `<html lang>` switching.** What: in `setLang`, also set
  `document.documentElement.lang = lang === 'bn' ? 'bn' : 'en'`. Why: D4 bug. Done-when: toggling
  EN updates `document.documentElement.lang` to `en`.
- **S3.2 Modal a11y.** What: focus trap + Escape-to-close + scroll lock + return focus to trigger for
  delete-account (and any future) modal. Why: C2/D12. Done-when: axe clean on modal; Escape closes;
  tab cycles within dialog.
- **S3.3 Contrast & type audit.** What: run a contrast check on all token pairs; bump `--muted`/
  badge colors if < 4.5:1; verify focus ring visible on all controls. Why: D3/D12. Done-when:
  `jest-axe` passes on every page; contrast report attached.
- **S3.4 Add `jest-axe` to vitest.** What: render each page in jsdom, assert `toHaveNoViolations`.
  Why: D12/D17. Done-when: a11y test suite runs in CI; zero violations.
- **S3.5 i18n completeness pass.** What: remove dead ternary/hacky `.replace` in `StudentDashboard`;
  ensure every user-facing string goes through `t()`; add a missing-keys lint (keys present in bn+en).
  Why: C1/D4. Done-when: no hardcoded BN strings outside `i18n.ts`; CI fails on missing EN key.

### PHASE 4 — Forms, feedback & onboarding UX
- **S4.1 Form validation UX.** What: inline field errors with `aria-describedby`, password strength
  meter, confirm-password field, server-error mapping per field. Why: D10/C2. Done-when: invalid
  email/shorts show inline message tied to input; strength meter visible.
- **S4.2 Onboarding / first-run.** What: a 1-screen welcome + role-based tip cards; guided "ask your
  first question" CTA in empty chat; sample prompt chips. Why: D20. Done-when: new user sees guided
  path, not blank UI.
- **S4.3 Toast success patterns.** What: confirm on export/download started, quiz submitted, profile
  updated. Why: D11. Done-when: key actions show success toast.

### PHASE 5 — Performance, PWA & responsiveness
- **S5.1 Route lazy-loading.** What: `React.lazy` + `Suspense` per dashboard; keep `api/i18n` eager.
  Why: D15. Done-when: initial bundle < ~150KB gzip; route chunks separate.
- **S5.2 Real PWA.** What: author `public/sw.js` (cache-first app shell, network-first API),
  `public/manifest.webmanifest` with name/icons/theme, and `public/icon.svg` + 192/512 PNGs. Verify
  offline shows cached shell + queued actions. Why: D16. Done-when: Lighthouse PWA pass; offline
  banner pairs with actual cached shell.
- **S5.3 Responsive refinement.** What: add `≥1024px` comfortable max-widths, tablet breakpoint,
  larger touch targets on mobile, safe-area insets. Why: D6. Done-when: manual pass on 360/768/1280.

### PHASE 6 — Frontend observability & quality net
- **S6.1 Error tracking.** What: add Sentry (or GlitchTip) with `beforeSend` scrubbing PII; hook
  `window.onerror` + React error boundary. Why: C1/D18. Done-when: a thrown error creates an issue;
  no secrets in payload.
- **S6.2 Privacy-friendly analytics.** What: minimal event telemetry (screen_view, quiz_started,
  msg_sent, error) behind consent; no PII. Why: D18. Done-when: dashboard shows funnels; respects
  Do-Not-Track.
- **S6.3 Test expansion.** What: component tests for each page (render + key interaction), visual
  regression (Chromatic/Playwright screenshot), and **Playwright e2e** for the critical persona
  journeys (register→chat→quiz→progress; parent link; admin purge). Why: D17/C1. Done-when: CI runs
  unit+component+e2e; e2e green on staging.
- **S6.4 Security hardening (frontend).** What: plan migration of auth token to httpOnly cookie
  (backend change) to cut XSS token-theft; until then, add CSP header + `X-Content-Type-Options` and
  sanitize any markdown HTML. Why: D19. Done-when: CSP present; markdown sanitized.

### PHASE 7 — Launch readiness & docs
- **S7.1 Frontend CI.** What: add to `ci.yml` — typecheck, vitest, playwright, lighthouse budget,
  axe. Why: keeps gains. Done-when: PRs block on frontend checks.
- **S7.2 Deploy & smoke.** What: deploy web to the same host/origin as API (or CDN), verify SPA
  fallback, TLS, health. Why: closes G6. Done-when: `https://<domain>` loads; happy path e2e green.
- **S7.3 Docs.** What: update README with UX/accessibility status; add `CONTRIBUTING` design-system
  guide; record Lighthouse/a11y reports in `docs/`. Why: handoff. Done-when: docs reflect reality.

---

## PART F — ENSURE NOTHING IS MISSING (master checklist)

Backend (from validation, still owned): NCTB rights · Gemini paid/rotate · domain/TLS/SMTP · commit/tag.
Frontend (this roadmap): S1.1–S1.4 · S2.1–S2.5 · S3.1–S3.5 · S4.1–S4.3 · S5.1–S5.3 · S6.1–S6.4 ·
S7.1–S7.3.

Cross-cutting "don't forget": 
- Lighthouse perf ≥ 90, a11y ≥ 95, SEO/best-practices ≥ 90 on the deployed URL.
- No `catch(()=>undefined)` remains; every async path has loading/error/empty.
- `<html lang>` tracks UI language; axe clean; contrast ≥ 4.5:1.
- Markdown+KaTeX render; citations preserved.
- PWA installs; offline shell works; manifest + icons present.
- e2e covers all four personas; visual regression baseline exists.
- Error tracking + privacy analytics live; no PII leaked.
- CSP + sanitized markdown; token hardened (planned).

---

## PART G — VISUAL / INTERNATIONAL-LEVEL DIRECTION (target)

- **Look:** Calm, trustworthy, "learning" tone. Deep green primary (keep brand), warm neutral
  surfaces, generous whitespace, rounded-2xl cards, soft shadows, one accent for actions.
- **Type:** Noto/Hind Bengali for BN; Inter for EN/latin numerals; clear type scale; comfortable
  line-height for Bangla.
- **Icon/Illustration:** line-style SVG icons (currentColor), friendly empty-state illustrations.
- **Motion:** purposeful, ≤300ms, reduced-motion safe.
- **Feel:** Duolingo/Khan/Quizlet-grade — guided, encouraging, legible on low-end phones, bilingual
  without friction.

---

## SUMMARY VERDICT (updated)
Current = **usable MVP, verdict B**. To reach **international-level production grade** you must
execute Phases 1–7 above (≈ 30 concrete steps). The backend is largely ready; the frontend is the
primary gap (resilience, design system, a11y, content rendering, testing, PWA). No step in this
document is optional for the stated "international level / best UI-UX" bar.
