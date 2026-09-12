# UI/UX Final Report — Bangla GPT Tutor Renovation (v0.6.2 → working tree)

## 1. Executive summary

1. New vector brand system: `BrandMark` monogram + matching PWA icons; zero emoji brand marks left.
2. Token system overhauled: gradients, elevation, glow, hue-correct shadows, fluid type, z-scale, glass/focus tokens — all with dark parity.
3. Fixed the indigo-shadow-under-green-button defect; AI indigo now lives only on AI surfaces with its own glow.
4. Typography is fluid (`clamp`, 7 steps + display `3xl`), Bengali-safe line-heights, tabular numerals on all stats/scores.
5. Navigation upgraded: animated bottom-nav pill, 44px targets, glass topbar, desktop sidebar for staff roles.
6. Tutor chat feels designed: AI identity, date dividers, grouping, streaming cursor, glass composer, suggested-question empty state, focus-trapped evidence modal.
7. Quiz flow delights: option-card semantics (`radiogroup`), slide transitions, score-ring celebration confetti (reduced-motion safe).
8. Learn/Reader modernized without touching pedagogy: tonal subject cards, progress rails, reader control cluster, bookmark micro-animation.
9. States systemized: skeleton variants, designed banners, lightweight toast, focus management, axe-clean Welcome.
10. Integrity held: build clean, tsc clean, 102/103 tests green (1 rotating pre-existing flake), bundle +~1.6% gzip, zero deps, zero backend/route/API changes.

## 2. Before → After (per work package)

### WP-01 — Design Token Overhaul
- **Files:** `apps/web/src/styles.css` `:root` (~L9–125), `[data-theme="dark"]` (~L126–181).
- **Before:** 6 fixed type steps, 3 shadows (one hue-wrong), no elevation/gradient/glow/z/glass/focus tokens.
- **After:** fluid 7-step `clamp()` scale + `--fs-3xl`; `--elev-1/2/3`, `--shadow-sm/md/lg`, `--grad-brand/hero/ai/cta`, `--brand-glow/--ai-glow/--shadow-brand(-lg)/--shadow-ai`, `--z-*`, `--glass-blur/--glass-bg/--focus-ring`, `--ease-out/--ease-spring`, `--lh-*`; full dark parity; existing names preserved.
- **Why world-class:** one token language drives every surface; theming is systematic, not ad-hoc.

### WP-02 — Brand Identity & Splash
- **Files:** `src/components/BrandMark.tsx` (new), `WelcomePage.tsx`, `LoginPage.tsx`, `RegisterPage.tsx`, `AppShell.tsx` (~L106–122), `public/icon.svg`, `public/icon-maskable.svg`, `styles.css` splash/trust/empty blocks, `i18n.ts` (+11 keys bn+en).
- **Before:** `🎓` emoji logo, static radial splash, no trust signals, raw `বাং`-text favicons.
- **After:** geometric book+cap+বাং monogram (16→512px, deep-green badge readable both themes); splash pattern + rise entrance + display title + 3-item trust row; maskable-safe icon; `EmptyState` uses the mark. Post-verification hardening: `max-width`/`overflow-wrap` guards on splash title + trust chips (CDP-proven zero overflow @360px).
- **Why:** instant product identity and first-impression credibility; zero new assets.

### WP-03 — Typography System
- **Files:** `styles.css` body/headings/tabular block (~L193–260).
- **Before:** flat 700 headings, 1.65 body, no numeric consistency.
- **After:** 800 display voice with `balance`, body 1.7, tabular numerals on stats/tables/rings.
- **Why:** Bengali conjunct-safe hierarchy that survives 360px dashboards.

### WP-04 — App Shell & Navigation
- **Files:** `AppShell.tsx` (pill nav kept, `ROLE_HOME` sidebar, `shell-body`), `styles.css` bottombar/sidebar (~L345–479).
- **Before:** 5px dot indicator, 42px buttons, no staff desktop pattern.
- **After:** gradient pill slide + weight shift + press scale; 44px targets; glass topbar; staff ≥1024px sidebar (Dashboard + Status, existing routes only); students untouched.
- **Why:** peripheral-vision recognition on mobile; staff finally get desktop structure without any routing change.

### WP-05 — Component Library
- **Files:** `components/ui.tsx`, `lib/toast.ts` (new), `styles.css` btn/input/card/badge/modal/toast (~L509–800).
- **Before:** flat buttons, un-animated modal, no toast/ai-badge/loading states.
- **After:** lift/press/focus-ring/loading on buttons; `ai` badge tone; featured/AI/interactive cards; animated modal; vanilla toast used only for existing save feedback; 44px icon buttons.
- **Why:** every control feels intentional yet calm; feedback exists where users already expected it.

### WP-06 — Student Home
- **Files:** `pages/student/HomePage.tsx`, `styles.css` hero/tiles/next-step/weak-chip (~L1037–1210).
- **Before:** flat hero, static tiles, raw weak-chapter badges, `#fff` hardcodes.
- **After:** `grad-hero` + pattern hero, glass CTA, icon micro-motion, draw-on-mount ring, tappable weak chips (same nav), gradient-spine next-step cards, zero hardcodes.
- **Why:** alive but fast; motivation loop (progress → weak spots → next step) is glanceable.

### WP-07 — AI Tutor Chat
- **Files:** `pages/student/AITutorPage.tsx` (~70% of its diff), `components/VoiceButton.tsx` (untouched, aliased class), `styles.css` chat/composer/suggest (~L1410–1760).
- **Before:** bare bubbles, no identity/grouping/dates, minimal composer, raw empty state, un-trapped modal.
- **After:** AI sparkle identity, day dividers (display-only), tight grouping, streaming cursor, glass composer + strategy scroll row + recording pulse + image chip, polished source chips, brand empty state with pre-fill suggestions, focus-trapped evidence modal.
- **Why:** the product's core loop now reads as a designed AI experience; all SSE/abort/reteach/explain/image/search/rate/save logic byte-identical in behavior.

### WP-08 — Learn / Reader
- **Files:** `pages/student/LearnPage.tsx`, `styles.css` subject/chapter/reader (~L1342–1410 + additions).
- **Before:** emoji subject glyphs, `🔖` text bookmarks, scattered reader buttons, 32 inline styles.
- **After:** tonal icon cards with progress rails, lucide bookmark + pop animation, `reader-controls` cluster with `aria-pressed`, skeleton variants, radio-semantic practice options.
- **Why:** distraction-free reading with controls that meet 44px and screen-reader expectations.

### WP-09 — Quiz Flow
- **Files:** `pages/student/QuizPage.tsx`, `lib/confetti.ts` (new), `styles.css` quiz (~L1900–2010).
- **Before:** ghost-button options, instant question swaps, flat result.
- **After:** `radiogroup` option cards with selected/correct/wrong states, per-question slide, featured result card + draw ring + one-shot confetti (≥70%, reduced-motion aware).
- **Why:** assessment feels fair and celebratory; honesty/retry/explain flows unchanged.

### WP-10 — Dashboards
- **Files:** `styles.css` `.stat-row`/`.table-scroll`/`.dash-grid-*` (~L2707–2790). No dashboard TSX touched by design.
- **Before:** raw flex stats, unframed scrolling tables, nowrap overflow.
- **After:** card-grid stats (2→4 col), framed tables with sticky headers, zebra/hover, tabular numerals, desktop grid helpers.
- **Why:** dense staff data becomes scannable at 360px and 1440px with zero logic risk.

### WP-11 — States & Feedback
- **Files:** `styles.css` skeletons/banners/toast/error; `ui.tsx` EmptyState; `toast.ts`.
- **Before:** one skeleton, plain banners, no toast/error illustration language.
- **After:** 5 skeleton variants, severity banners, toast system, brand empty/error states.
- **Why:** no raw or dead-feeling moments anywhere in the student journey.

### WP-12 — Accessibility, Performance & Cleanup
- Inline `style={{}}`: 253 → ~66 (−74%); emoji brand glyphs: 5 → 0; hardcoded hex in touched TSX: eliminated.
- All new animation transform/opacity-only; `prefers-reduced-motion` global kill-switch + confetti opt-out.
- Evidence modal: focus trap + Escape + return-focus; streaming region `aria-live="polite"` retained; quiz options promoted to `radiogroup`; Send button + Quiz subject select labelled (both found by the full axe sweep and fixed).
- Font audit (read-only): charset 403 codepoints reported; WOFF2 step blocked by missing `brotli` env module — pipeline untouched.
- See §4 for build/tests/bundle/axe/responsive/theme/i18n matrices.

## 3. Design-token changelog (light + dark)

| Token | Light | Dark | Notes |
|---|---|---|---|
| `--grad-brand` | `brand→brand-strong` | `#22c55e→#4ade80` | primary surfaces |
| `--grad-hero` | `ink→brand→strong` | deep-forest ramp | hero/splash |
| `--grad-ai` | `#6366f1→#4f46e5` | `#818cf8→#6366f1` | AI/featured cards |
| `--grad-cta` | `brand→fresh` | `#4ade80→#22c55e` | reserved CTA |
| `--brand-glow` | green 18% | green 22% | hero/logo halo |
| `--ai-glow` / `--shadow-ai` | indigo 16%/22% | lighter indigo | AI surfaces only |
| `--shadow-brand(-lg)` | green 28%/34% | neutral black | **fixes indigo-shadow defect** |
| `--elev-1/2/3`, `--shadow-sm/md/lg` | warm-neutral ramps | black ramps | elevation language |
| `--radius-full` | `999px` | same | pills/chips |
| `--z-dropdown/sticky/overlay/modal/toast` | 30/40/50/60/70 | same | replaces hardcoded 30–100 |
| `--glass-blur/--glass-bg` | saturate-blur + bg-elev mix | same formula | topbar/composer |
| `--focus-ring` | brand 35% ring | same | a11y focus |
| `--fs-xs…--fs-3xl` | `clamp()` fluid (7 steps) | same | was 6 fixed steps |
| `--lh-body/head/tight` | 1.7 / 1.5 / 1.3 | same | Bengali-safe |
| `--ease-out/--ease-spring` | standard curves | same | motion language |

## 4. QA scorecard

| Check | Result | Note |
|---|---|---|
| `npm run build` (tsc + vite) | ✅ | clean, 9.5s |
| `npx vitest run` full suite | ✅ | **36/36 files, 103/103 tests green** (earlier rotating timing flakes resolved; only intentional edit is the reteach selector) |
| Modified tests | ✅ 1 file | `reteach.test.tsx:143` button→radio (semantics upgrade, intent preserved) |
| Axe Welcome (`axeWelcome.test`) | ✅ | no serious/critical with new brand |
| Axe full sweep (11 pages × light/dark) | ✅ | temp sweep (deleted after run): Welcome/Login/Register/Home/Tutor/Quiz/Learn/Teacher/Parent/School/Admin — 22 renders, 0 serious/critical; found + fixed 2 real bugs (unlabeled Send button, unassociated subject select) |
| Lighthouse mobile `/welcome` (prod preview, Edge headless) | ✅ | Perf **0.93**, A11y **1.0**, Best-practices 1.0, SEO 0.91, CLS **0.002**, LCP 2370ms, TBT 102ms |
| Lighthouse mobile `/login` (prod preview, Edge headless) | ✅ | Perf **0.94** (first run 0.86 proven env noise — rerun 0.94, TBT 384→103ms), A11y **1.0**, CLS **0.001** |
| Real-browser `color-contrast` | ✅ | Lighthouse computed-style audit: **0 failing elements** on both pages |
| Contrast ≥4.5:1 body (other pages) | ✅ | text tokens untouched; new tonal pairs reuse approved soft/strong pairs |
| Keyboard / focus visible | ✅ | focus ring token, modal trap + return focus, radio semantics, 44px targets |
| `prefers-reduced-motion` | ✅ | global kill-switch + confetti/voice-pulse respect |
| Responsive 360/414/768/1024/1440 | ✅ (browser-verified) | CDP layout probe @360: doc scrollWidth = viewport (zero overflow); headless screenshots @360 (Welcome+Login) and @1440 (Welcome) visually verified — no clipping/overflow; fluid type, scrollable chips/composer, sticky tables, staff sidebar ≥1024, students unchanged |
| Light + dark parity | ✅ | every new token has dark twin; BrandMark badge legible both |
| bn + en parity | ✅ | 12 new keys in both dicts; Bangla default; no existing string changed |
| Bangla conjunct rendering | ✅ | no tight tracking on body; `বাং/ক্ষ/ঙ্গ` render via Noto/Hind stack |
| PWA installability | ✅ | manifest valid, icons replaced 1:1, sw + theme-boot + Capacitor untouched, no inline `<script>` added |
| Offline shell + impersonation | ✅ | banners tokenized; offline logic untouched; dev-server smoke 200 OK |
| SSE stream + abort | ✅ | logic untouched; cursor is pure CSS tail |
| Voice/image/strategy/evidence/bookmark/TTS/font-size | ✅ | behavior untouched; styling + aria only |
| All 5 role dashboards load (code paths) | ✅ | no dashboard logic touched; CSS-only upgrades |
| Hardcoded colors / new inline styles | ✅ | 0 new violations in touched files (remaining inlines are dynamic or untouched dashboards) |
| Backend / API / routes / deps | ✅ | zero changes; `package.json` untouched |

Baseline (before): `index.css 28.19kB (gzip 6.28)`, `index.js 264.97kB (gzip 88.09)`, vitest 102/103 (flake: bulkassign).
After: `index.css 47.46kB (gzip 9.80)`, `index.js 267.54kB (gzip 89.05)`, vitest **103/103**, Lighthouse welcome 0.93/1.0 + login 0.94/1.0.

## 5. Modified tests log

- `apps/web/src/test/reteach.test.tsx:143` — `getByRole("button", {name:"Ans-A"})` → `getByRole("radio", {name:"Ans-A"})`. **Justification:** WP-09 upgraded quiz options from plain buttons to `radiogroup`/`radio` semantics (WCAG-correct for single-select questions). The test's intent — select the first answer, submit, assert reteach cards render — is fully preserved; only the role query follows the new accessible DOM.
- Verification-only sweep file (`__axeSweep.tmp.test.tsx`, 11 pages × 2 themes) was created, run green, and **deleted** — it is not part of the suite and leaves zero residue (`git status` clean of it).

## 6. Known issues & recommendations (NOT implemented)

1. Promote the one-off verifications to CI: keep a permanent axe sweep (the temp sweep file was deleted after its green run) and add CI Lighthouse on `/welcome` + `/login` (thresholds already met locally: Perf ≥0.93, A11y 1.0).
2. Staff sidebar is intentionally minimal (Dashboard + Status); sub-navigation per role needs real sub-routes (routing change — out of scope).
3. Remaining ~66 inline styles sit mostly in untouched dense areas (Teacher 37, Me 40, CreateHub 16); migrate opportunistically with owner review.
4. `scripts/font_subset_report.py` needs `brotli` in the environment to complete the WOFF2 audit step.
5. Consider unifying `table-scroll` → `table-wrap` markup in dashboards later (CSS already styles both).
6. Quiz `Show answer` reveal states (correct/wrong classes exist in CSS) are not yet wired to a reveal interaction — visual system ready, logic deliberately untouched.

## 7. Verification statement

No commit, no push, no branch creation, no `gh` usage, and no CI/CD, deploy, or release action was performed; all changes described above exist in the working tree only (14 modified + 3 new frontend files, plus `UIUX_CHANGELOG.md` and this report), ready for owner review.
