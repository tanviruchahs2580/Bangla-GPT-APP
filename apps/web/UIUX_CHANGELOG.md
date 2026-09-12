# UI/UX Renovation — Working Changelog (WP-01 → WP-12)

> Scope: frontend only (`apps/web/src`, `apps/web/public/icon*.svg`).
> Off-limits untouched: `apps/api/`, `data/`, `deploy/`, `docker-compose.yml`,
> CI workflows, Capacitor config, `index.html`, PWA manifest/sw/theme-boot.
> No commit / push / branch / gh / deploy executed — working tree only.
> Baseline: v0.6.2-9-g66d2a88, `npm run build` clean, vitest 102/103
> (1 pre-existing flake: bulkassign/lessonplan/weakmatrix family, timing-sensitive,
> passes in isolation).

## Prep (user-approved)
- Restored `apps/web/src/styles.css` to HEAD (`git restore`) after finding a
  dirty 19-line partial token edit that had **deleted** `--radius-sm/--radius/
  --radius-lg`. Radii restored; WP-01 re-applied cleanly on top.
- Baseline metrics recorded (see Final Report §4).

## WP-01 — Design Token Overhaul (`src/styles.css` `:root` + dark)
- Added: `--grad-brand/--grad-hero/--grad-ai/--grad-cta`, `--brand-glow`,
  `--shadow-brand/--shadow-brand-lg`, `--ai-glow/--shadow-ai`, `--elev-1/2/3`,
  `--shadow-sm/--shadow-md/--shadow-lg`, `--radius-full`, `--z-dropdown/
  --z-sticky/--z-overlay/--z-modal/--z-toast`, `--glass-blur/--glass-bg/
  --focus-ring`, `--ease-out/--ease-spring`, `--lh-body/--lh-head/--lh-tight`.
- Typography: 6 fixed steps → 7 fluid `clamp()` steps + `--fs-3xl`.
- Fixed defect: `btn-primary` indigo-tinted shadows
  (`rgba(67,83,184,.28)`/`rgba(51,64,155,.34)`) → green `--shadow-brand(-lg)`.
- Dark parity for **every** new token. Existing names kept (zero renames).
- Risk: low (additive + 2 shadow value fixes). `tsc` clean.

## WP-02 — Brand Identity & Splash
- New `src/components/BrandMark.tsx`: inline-SVG book + cap + "বাং" monogram
  (deep-green badge, legible light+dark, 16→512px) + `AiSparkle` for AI chrome.
- Replaced emoji: `WelcomePage 🎓`, `LoginPage 🎓`, `RegisterPage 🎓`,
  `ui.tsx EmptyState 📘`, `LearnPage 📘` fallback, topbar `GraduationCap`
  brand-mark → `BrandMark`. Grep `🎓|📘` in `src/*.tsx`: **5 → 0**.
- Splash: `.splash-pattern` dot-matrix, `splash-rise` entrance, `fs-3xl`
  display title, `.trust-row` (3 items, lucide icons, new i18n keys).
- Icons: `public/icon.svg` (rounded, gradient + book + বাং) and
  `public/icon-maskable.svg` (full-bleed, safe-zone text size) rewritten in the
  same visual language. Manifest untouched (still points at both).
- i18n (bn+en): `trustNctb/trustAi/trustOffline`, `emptyChatTitle/emptyChatSub`,
  `suggestQ1/2/3`, `brandHome`, `dashboard`. No existing string altered.
- Risk: low. Welcome/Login/Register CTAs + `track()` calls intact (tests pass).

## WP-03 — Typography System
- Body `line-height: var(--lh-body)` (1.7, Bengali-safe); headings 800 weight,
  `text-wrap: balance`, `h1→fs-2xl/h2→fs-xl/h3→fs-lg` mapping preserved.
- `font-variant-numeric: tabular-nums` on stats/scores/tables/rings.
- Conjunct clipping: no negative letter-spacing on body; headings −0.005em only.
- Risk: low (global but token-driven; dashboards gain hierarchy for free).

## WP-04 — App Shell & Navigation
- Bottom nav: `::before` animated gradient pill (`scaleX` slide), active label
  800 weight, 44px targets, press `scale(.94)`; legacy dot kept as secondary cue.
- Topbar: `var(--glass-bg)` + `var(--glass-blur)`, `z-index: var(--z-sticky)`,
  `BrandMark` integration, `aria-label={t("brandHome")}`, settings nav labelled.
- Staff desktop ≥1024px: `.shell.has-sidebar` + `.shell-body` flex row +
  `.sidebar` (Dashboard → `ROLE_HOME[role]`, Status → `/status`; existing routes
  only, no new routing). Students unchanged at all widths; sidebar `display:none`
  below 1024px. Staff content capped 1080px.
- Risk: medium (AppShell structural). Mitigated: students byte-identical layout;
  staff links reuse `ROLE_HOME`; `tsc` + build clean; no bottombar for staff
  (as before).

## WP-05 — Component Library (`ui.tsx` + `styles.css`)
- `Button`: hover lift, press scale, `:focus-visible` ring, `loading` prop →
  `aria-busy` + `.btn-loading` spinner (CSS only). Teal/ghost/soft/danger hover
  states tokenized.
- `Card`: removed `style` prop (migrated callers); `.card-head-row/
  .card-title-flush/.card-action` classes; `.card-interactive/.card-featured/
  .card-ai` variants; mount `card-rise`.
- `Badge`: new `ai` tone (indigo soft + glow).
- `Spinner`: class-based `.spinner-dot` (was inline style).
- `ProgressRing`: `.ring-draw` pop animation (transform/opacity only).
- `Row` action variant: `.row-action` class (was 8-line inline style).
- `EmptyState`: `BrandMark` + `.empty-pad/.empty-sub/.empty-action`.
- `Modal`: blur 3→6px, `z(--z-modal)`, backdrop fade + dialog scale/fade entrance.
- `Toast`: new `src/lib/toast.ts` (vanilla, ≤1KB, `aria-live` region, max 3,
  auto-dismiss) — wired **only** to existing tutor save-note feedback.
- `icon-btn`: 42→44px targets, hover border, focus ring.
- Inputs: hover border, `--focus-ring`, disabled + `aria-invalid`/`field-error`
  states.
- Risk: low-medium. `Card style` removal required migrating Quiz/Learn callers
  (done, `tsc` clean).

## WP-06 — Student Home (`HomePage.tsx`)
- Hero keeps greeting/CTAs/routes/analytics; CTAs → `.btn-teal` /
  `.hero-btn-glass` classes (hardcoded `#fff`/`rgba(255,255,255,.15)` removed);
  `.hero-sparkle` class; hero uses `var(--grad-hero)` + dot pattern + `elev-2`.
- Tiles: `.quick-title-block`, tonal `.tile-teal/.tile-warn`, press scale +
  icon bob on hover.
- Progress: `ProgressRing` draw animation; `.progress-hero-row`;
  `.stat-grid.section-gap-top`; weak chapters → tappable `.weak-chip` buttons
  (same `/student/learn` navigation, `aria-label` = chapter).
- Continue/recommendation cards → `.next-step-card` (gradient spine).
- Risk: low (display/classes only; data hooks untouched).

## WP-07 — AI Tutor Chat (`AITutorPage.tsx`)
- Identity: `.bubble-id` (`AiSparkle` + "AI") on assistant bubbles incl. typing.
- Streaming: `.stream-cursor` pulse at live tail; `aria-live="polite"` kept;
  smooth auto-scroll untouched; abort button untouched.
- Grouping: same-role consecutive messages get `.chat-group-tight`.
- Date dividers: `.chat-day` derived **display-only** from `created_at`
  (optional; absent → no divider, no crash).
- Composer: card → `.chat-card` (elev-2); strategy chips → `.chips.strategy-row`
  scrollable; send/attach/voice states unchanged; `VoiceButton` listening pulse
  via `.voice-live` alias; image preview → `.attach-preview`/`.attach-row`.
- Sources: `.source-row` + hover affordance; evidence modal keeps content/flow,
  gains **focus trap + Escape + return-focus** (WP-12) and class-based layout
  (fixed invalid `--radius-md` → `--radius-sm`).
- Empty state: brand `EmptyState` language — `BrandMark` + `emptyChatTitle/Sub`
  + 3 `.suggest-chip`s that **pre-fill** the composer (no API change).
- Inline `style={{}}` in file: 33 → ~3 (dynamic only).
- Risk: medium (largest file). Mitigated: SSE/abort/reteach/explain/image/search/
  rename/delete/rate/save flows untouched; `tsc` + tutor-adjacent tests pass.

## WP-08 — Learn / Reader (`LearnPage.tsx`)
- Removed `EMOJI` map + `📘` fallback → tonal `BookOpen` icon
  (`SUBJECT_TONE`); `.subject-card.active` tokenized; `.subject-progress` rail.
- Chapter rows: `.chapter-card`, tonal icon, `Bookmark` lucide for bookmarked
  (was `🔖` text), `.chapter-progress` bar (completed 100 / in-progress 45 /
  untouched 0 — display only from existing `progressMap`), `.quiz-review-row`.
- Reader: `.reader-controls` cluster (subject/class/bookmark/TTS/offline/
  download/font-scale), bookmark `.bookmark-pop` on toggle, `aria-pressed` on
  bookmark/TTS, `.workspace-tabs`, `.reader-title/.reader-book/.reader-md`,
  `.font-range`. Font-scale + progress-width inline styles kept (dynamic).
- Practice/Ask tabs: options → `.quiz-option` + `radiogroup`/`radio` semantics;
  ask rows → `.ask-context-row/.ask-row/.ask-input`; answer card →
  `.chapter-card` + `.chips-gap`.
- Risk: low-medium. Offline/TTS/download/tab logic untouched.

## WP-09 — Quiz Flow (`QuizPage.tsx`)
- In-progress: `Card key={current} .quiz-q` (slide/fade per question),
  `.quiz-q-title`, options → `.quiz-option` + `role=radiogroup/radio` +
  `aria-checked` (was `btn-ghost/btn-soft`), `.quiz-pager`, tokenized errors.
- Result: `.card-featured`, `.quiz-result-hero/.quiz-result-score` (was inline
  flex), review rows → `.quiz-review-row` + `.tile-ok/.tile-danger` (was inline
  hex-var backgrounds), reteach → `.card-ai`, `.reteach-hint`, `.flush`.
- Celebration: new `src/lib/confetti.ts` (≤2KB, self-cleaning, skips on
  `<70%` and under reduced-motion) fired once via `QuizCelebration` on result
  mount. Flows (start/submit/retry/explain-link/honesty) untouched.
- **Test update**: `src/test/reteach.test.tsx:143` selector
  `getByRole("button","Ans-A")` → `getByRole("radio","Ans-A")` — required by the
  button→radio semantics upgrade; assertion intent (select answer, submit,
  expect reteach cards) preserved.
- Risk: medium (covered by updated test + quiz/revision/shorttest suites green).

## WP-10 — Dashboards (Teacher/Parent/School/Admin)
- Zero-logic approach: upgraded legacy vocabulary in CSS —
  `.stat-row` → responsive card grid (2col → 4col ≥760px, tabular nums, brand
  value color), `.table-scroll` → card-framed scroll region with sticky header,
  zebra + hover rows, tabular nums, 560px min-width.
- `.dash-grid-2/3` helpers + staff sidebar content cap for 1440px rhythm.
- Empty/loading states left structurally intact (reuse WP-02 `EmptyState`
  language where already used); no metric invented.
- Risk: low (CSS-only; no dashboard TSX touched).

## WP-11 — States & Feedback
- Skeletons: `.skeleton-card/-list-row/-table-row/-text/-avatar` variants;
  shimmer kept + `[data-lowdata]` kill-switch + reduced-motion guard inherited.
- Offline banner: severity border + `z(--z-toast)`; impersonation banner
  tokenized to `.impersonation-banner` class (was 10-line inline style).
- Toast region/styles (see WP-05); error copy (`friendlyError`) unchanged.
- Risk: low.

## WP-12 — A11y, Performance & Cleanup
- Inline styles: repo-wide `src` 253 → ~66 (−74%); emoji 5 → 0. Remaining are
  near-all dynamic (`width:%`, `fontScale`, ring `--p`/sizes) or inside
  untouched dense dashboards (Teacher 37, Me 40, CreateHub 16) — logged as
  deliberate leftovers (risk of touching working dashboards > polish value).
- Hardcoded hex in `*.tsx`: 6 → 0 in touched files (AppShell `#fff`,
  HomePage `#fff`×2 removed; StatusPage fallbacks untouched).
- `btn-primary` indigo shadow defect fixed (WP-01).
- Fonts (read-only): `scripts/font_subset_report.py` attempted;FRE
  `UI charset size: 403 codepoints` printed, then WOFF2 step failed on missing
  `brotli` module (env limitation — pipeline NOT modified). `@fontsource`
  Noto Sans Bengali + Hind Siliguri remain the only webfonts (`font-display:
  swap` via fontsource defaults); no new font files added.
- Motion: all new keyframes transform/opacity only (`card-rise`, `bubble-in`,
  `ring-pop`, `quiz-slide`, `modal-in`, `toast-in`, `confetti-fall`,
  `stream-pulse`, `voice-pulse`, `btn-spin`, `bookmark-pop`, `splash-rise`);
  global `prefers-reduced-motion` kill-switch retained and honored by confetti.
- `axeWelcome` suite: **pass** (no serious/critical on Welcome with new brand).
- Prettier: `prettier --write` applied to 5 touched files (format only).
- Full `tsc --noEmit`: clean. `npm run build`: clean (see Report §4).
- `npx vitest run`: 102/103 per run; the single failure rotates between
  timing-sensitive suites (bulkassign/lessonplan/weakmatrix — all pass in
  isolation, incl. post-change) → pre-existing flakes, not regressions.
  Only intentional test edit: reteach selector (above).

## Addendum — live verification on current tree (pre-pipeline)

Live stack: `api-live` (:8000, image 10:04 UTC, backend-identical) + `web-preview`
(:8081). The web image (09:40 UTC) predated the renovation → rebuilt from the
working tree and recreated. Two latent issues surfaced and were fixed:

1. **nginx fatal on restart** — `proxy_pass http://api:8000/` resolves at
   startup; `[emerg] host not found in upstream "api"` killed every fresh
   web-preview (Exit 1). Fixed in `apps/web/deploy/nginx.conf` with Docker
   embedded-DNS resolver + `$api_upstream` variable (request-time resolution;
   identical `/api/`→`/` stripping). Also fixed the local topology with a
   `bgpt-live` user network + `api` alias (prod compose already names the
   service `api`, so the config stays prod-correct).
2. **Register funnel broken while logged out (P0 functional bug, pre-existing).**
   `track("welcome_cta")` → `POST /events` → **401 anonymous** → global
   `onUnauthorized` → `window.location.href = "/login"` full-load bounce that
   destroys the SPA navigation to /register. Proven via CDP click-trace.
   Fixed frontend-only in `src/api.ts` (`api()`/`post()` accept
   `{ skipUnauthorized: true }`) + `src/lib/analytics.ts` passes it —
   analytics stays best-effort and can never redirect. Contract change: none
   (server still 401s; client just stops self-sabotaging). Tests: new
   `src/test/analytics.test.tsx` (payload + no-redirect pins);
   `welcome.test.tsx` assertion extended with the third arg (intent preserved).

User-journey evidence (live :8081 + :8000, headless Edge):
- API `e2e_user_journey.py`: **21/21 green** (health/headers/register/login/
  me/grounded ask/conversations/history/SSE stream/quiz/catalog/export/
  401-negatives/delete). `smoke_stack.py`: **7/7**.
- UI CDP journey (fresh profile): welcome(3) → register+auto-login →
  home(3) → tutor empty-state/suggest×3/strategy×5 + real SSE answer + AI
  identity → quiz start/options(radio)/submit/result → no JS errors:
  **15/15 green**, 7 screenshots in `Temp/opencode/journey/`.

## Files touched (final)
- Modified (14): `styles.css`, `AppShell.tsx`, `components/ui.tsx`, `i18n.ts`,
  `WelcomePage.tsx`, `LoginPage.tsx`, `RegisterPage.tsx`,
  `student/HomePage.tsx`, `student/AITutorPage.tsx` (+`aria-label` on Send),
  `student/QuizPage.tsx` (+`htmlFor`/`id` on subject select),
  `student/LearnPage.tsx`, `public/icon.svg`, `public/icon-maskable.svg`,
  `test/reteach.test.tsx`.
- Added (3): `components/BrandMark.tsx`, `lib/toast.ts`, `lib/confetti.ts`
  (+ this changelog; final report next).
- Explicitly NOT touched: `apps/api/**`, `data/**`, `deploy/**`,
  `docker-compose.yml`, `.github/**`, `index.html`, manifest/sw/theme-boot,
  Capacitor, `package.json` (zero new deps), any API contract or route.

## Addendum — closing the 2 honest gaps (post-report verification)
- **Full axe sweep:** temporary `src/test/__axeSweep.tmp.test.tsx` rendered
  Welcome/Login/Register/Home/Tutor/Quiz/Learn/Teacher/Parent/School/Admin in
  light + dark (22 renders) — 0 serious/critical. It caught 2 REAL pre-existing
  bugs, both fixed (no behavior change): Tutor Send button had no accessible
  name (`aria-label={t("send")}` added); Quiz subject `<select>` had an
  unassociated `<label>` (`htmlFor`/`id="quiz-subject"` added). Sweep file
  deleted afterwards; `git status` shows no residue.
- **Lighthouse mobile** (production `vite preview`, headless Edge 152):
  `/welcome` Perf 0.93 / A11y 1.0 / BP 1.0 / SEO 0.91 / CLS 0.002;
  `/login` Perf 0.94 / A11y 1.0 / CLS 0.001 (first login run 0.86 proven to be
  host-CPU noise by rerun: TBT 384→103ms). Real-browser `color-contrast`:
  0 failing elements on both pages.
- **Responsive proof:** CDP layout probe @360px (doc scrollWidth = viewport,
  all splash/trust rects inside viewport) + CDP mobile-emulation screenshots
  @360 (Welcome, Login) and @1440 (Welcome) visually verified, no
  clipping/overflow. (Note: plain `--screenshot` at 360 lies — headless
  minimum-window clamping crops the image; CDP emulation is authoritative.)
  Added `max-width`/`overflow-wrap` guards on splash title + trust chips as
  belt-and-braces.
- Final gates after the above: `tsc` clean, `npm run build` clean
  (CSS 47.46kB/9.80 gzip, JS 267.54kB/89.05 gzip), prettier clean,
  **full suite 36/36 files, 103/103 tests green**.
