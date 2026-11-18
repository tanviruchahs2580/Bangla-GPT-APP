# FONT_E5_PHASE2 — self-hosted webfonts, preload, metric-matched fallback

**Status:** engineering complete; visual regression evidence below; CI gates run on the PR
**Date:** 2026-11-18 · Branch `feat/mobile-platform-hardening`

---

## 1. What changed and why

The entire web font pipeline previously came from two npm packages
(`@fontsource/noto-sans-bengali`, `@fontsource/hind-siliguri`) imported as CSS
in `main.tsx`. This workstream replaces that with repository-owned assets and
keeps the on-wire behaviour identical where it matters:

| Change | Rationale |
|---|---|
| 10 WOFF2 binaries vendored into `apps/web/public/fonts/` (byte-identical copies of the `@fontsource` files, SHA-256 recorded) | removes the build/runtime dependency; stable URLs survive every deploy |
| `src/fonts.css` declares the `@font-face` set (same families, weights, `unicode-range`, `font-display: swap` as the package CSS) | rendering parity by construction |
| `index.html` preloads exactly one face: `noto-sans-bengali-bengali-400-normal.woff2` | the primary family's body-weight Bengali subset is the first meaningful text paint; one file, stable path, no hash staleness |
| latin-ext subsets **dropped** (6 files, ~29 KB) | no shipped string or realistic tutor output uses U+0100–02BA; uncovered codepoints fall to the system stack — the same behaviour as any webfont lacking a glyph. This was the headroom the earlier capacity-plan experiment already identified. |
| legacy `.woff` duplicates **dropped** (35 files, ~671 KB in every APK) | every supported engine takes the woff2 source; the duplicates were never fetched |
| metric-matched fallback faces added (measured, not guessed) | swap-window CLS guard — see §3 |
| `npm uninstall` of both `@fontsource` packages; lockfile updated via npm | B7 dependency cleanup; `package.json`/`package-lock.json` contain zero `fontsource` references |

## 2. Measurements (this HEAD, not historical numbers)

**Before** (baseline build at `d24719a`, measured 2026-11-18):

- dist shipped **69 font files**: 34 woff2 (637,400 B) + 35 legacy .woff (~671 KB).
  The 15 `@fontsource` woff2 = ~375 KB; the remainder is KaTeX (untouched scope).
- No preload; hashed asset URLs (`/assets/*-[hash].woff2`) invalidated font caches
  on every deploy (the SW font-FIFO exemption existed precisely because of this).

**After** (this branch):

- `dist/fonts/`: **10 woff2 = 346,060 B**; `dist/assets/` retains only KaTeX fonts
  (39 files, 256,168 B — unchanged).
- Preload: 1 file, 44,352 B — verified fetched **exactly once** (no duplicate download;
  the preload URL and the CSS URL are the same stable path).
- First-view Bengali cold transfer is materially unchanged (~55 KB for the primary
  face's bengali+latin 400 subsets — same binaries, same `unicode-range` gating).
  **The win is not first-view bytes**; it is: (a) −2 npm dependencies and ~2.4 MB of
  `node_modules`, (b) −671 KB of never-fetched `.woff` dead weight in every APK,
  (c) stable URLs → font caches survive deploys (no per-deploy refetch/SW eviction),
  (d) the preload + CLS guard. This is stated plainly per B6: no material payload win
  on the critical path; clear packaging/caching advantages instead.

**Zero third-party font egress** — verified in a real Chromium (§4): the only font
requests are same-origin `/fonts/*.woff2`; no `fonts.googleapis.com`/`fonts.gstatic.com`/CDN
request exists.

## 3. Metric-matched fallback (measured, not guessed)

`scripts/font_metrics.py` reads the actual SFNT metrics (fontTools + brotli) and
derives the descriptors with the fontaine formula. Measured 2026-11-18:

| Font | upm | hhea ascent/descent/gap | avg advance (em-normalised, 67-glyph Bengali charset) |
|---|---|---|---|
| Noto Sans Bengali Regular (shipped woff2, target) | 1000 | 917 / −408 / 0 | 0.6062 em |
| Nirmala UI (Windows system fallback, `Nirmala.ttc`) | 2048 | 2210 / −514 / 0 | 0.6603 em |

Derived descriptors (em-normalised — an earlier raw-advance ratio was wrong because
the two fonts use different upm; the script fixes and documents this):

- **Windows fallback** (`local("Nirmala UI")`, family `Noto Sans Bengali Fallback`):
  `size-adjust: 91.8%; ascent-override: 99.9%; descent-override: 44.45%; line-gap-override: 0%`
- **Android pin** (`local("Noto Sans Bengali")`, family `Noto Sans Bengali Fallback Local`):
  `size-adjust: 100%; ascent-override: 91.7%; descent-override: 40.8%; line-gap-override: 0%`
  — the system's own Noto Sans Bengali forced to the webfont's natural ratios, so OS-font
  version drift cannot shift layout mid-swap.
- **macOS/other:** neither `local()` resolves → falls through to the system stack.
  Documented limitation (least-harmful choice); no arbitrary percentages shipped.

The stack order in `--font` is
`"Noto Sans Bengali", "Noto Sans Bengali Fallback", "Noto Sans Bengali Fallback Local", "Hind Siliguri", …`
— platform selection happens by source availability (Windows resolves Nirmala; Android
skips it and resolves the local Noto pin), and both fallback faces sit **before** Hind
Siliguri so the swap window never pulls the second webfont family down.

## 4. Browser verification (real Chromium, Playwright)

`scripts/verify_fonts.mjs` serves the production build and loads a Bengali fixture
(conjuncts ক্ষ ত্র জ্ঞ শ্র ণ্ড, matras, Bengali + Latin numerals, mixed bn/en, ৳, danda,
weights 400/600/700) through the app's real built stylesheet:

- `VERIFY_FONTS: PASS` — Noto 400/600/700 loaded via `document.fonts`; Hind Siliguri
  declared and correctly left unloaded (nothing fell through to it — correct
  `unicode-range` behaviour); **0 external font requests**; preload face fetched exactly 1×.
- Screenshot evidence: `font-fixture-after.png` (fonts loaded) — conjuncts and matras
  shape correctly, no tofu/clipping.
- **Fallback-period test:** with every `*.woff2` request blocked, the page renders
  through `Noto Sans Bengali Fallback` (loaded=true) — real Bengali text during the swap
  window, not invisible/tofu text (`font-fallback-period.png`).

Harness note (recorded because it cost a false failure): fonts are CORS-required
resources; a `page.setContent`/`about:blank` harness fails every face with an opaque
fetch error. The fixture is served same-origin by the verification server.

## 5. Acceptance gates (B8)

| Gate | Status |
|---|---|
| No `@fontsource/*` imports or dependencies | PASS — `grep` over `package.json`, `package-lock.json`, `src/`: 0 hits |
| Self-hosted, licensed, notices updated | PASS — binaries + `LICENSE-*.txt` committed; `THIRD_PARTY_NOTICES.md` rewritten for the vendored state |
| Preload exact, non-duplicated, justified | PASS — 1 face, stable path, fetched exactly once in Chromium |
| Fallback metrics measured | PASS — `scripts/font_metrics.py`, values in §3 |
| Bengali shaping regression | PASS — fixture screenshots; repo visual e2e suite runs against existing baselines in CI |
| `npm ci`, TS, ESLint, Vitest, Knip, build | knip + full suite run at Phase 6 and on CI; build verified locally (§2) |
| Android bundle serves local fonts | the APK packages `dist/` wholesale — `dist/fonts/` is inside it; no remote font host exists anywhere in the bundle |

## 6. Residual notes

- `docs/capacity_plan.md` gains a Phase 2 section; the historical pilot decision text is
  preserved as history, not silently rewritten.
- If a face is ever upgraded, `public/fonts/README.md` documents the regeneration
  procedure (never a font mirror site; re-measure the fallback descriptors).
