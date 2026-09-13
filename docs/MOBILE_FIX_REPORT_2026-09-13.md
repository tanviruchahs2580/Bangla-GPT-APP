# WAVE-5 — Mobile Responsive Repair — Final Report (v0.9.1)

**Date:** 2026-09-13 · **Scope:** `apps/web` CSS only · **Trigger:** user-reported broken layout on Android Chrome after login (screenshot, ~360px viewport)
**Directives:** features/logic untouched (zero TSX diff), all 126 tests kept green, CI/CD executed per SOP.

---

## 1. Issues found (as a user, 360×800 audit on the live deployment)

| # | Defect | Root cause |
|---|--------|-----------|
| 1 | **Topbar broken on every logged-in page** — brand wrapped to 3 lines, username wrapped, icon buttons scattered across 2+ rows spilling out of the 64px bar over the page; search box squeezed to a sliver | `.topbar` is a fixed-height no-wrap flex bar; its content (brand ≈180px + search + username ≈90px + 5×44px icons ≈340px ≈ **616px total**) cannot fit any phone viewport. Children wrapped *inside* the bar (`.row-flex` wraps; brand text wraps) while the bar itself stayed 64px → painted overflow |
| 2 | **Staff (teacher) navigation missing entirely on phones** — sidebar is `display:none` <1024px with no substitute; teachers could not reach Create/Classes/Assessments/Analytics at all | Mobile-first layout only ever provided bottom-nav for students; staff got links only in the desktop sidebar |
| 3 | **Home snapshot card + hero prompt squeezed** — "এখনো কোনো কুইজ দেওয়া হয়নি" rendered one-word-per-line; prompt input cramped | Fixed-width ring (72px) + button (~130px) left ~70px for text in the row; prompt input+button shared one 345px row |

Not broken (verified, left alone): landing, login/register split layout, quick tiles, bottom nav, tutor/quiz/learn/me content columns, dark mode, horizontal page overflow (none — the damage was contained inside the topbar).

## 2. Fixes (all CSS, new `15c. WAVE-5` section in `styles.css`)

1. **Two-row topbar ≤960px:** row 1 = brand ↔ actions (`nowrap`, `margin-left:auto`), row 2 = full-width search (`order:3; flex:1 1 100%`). Brand: `nowrap + ellipsis + min-width:0`, `fs-md` ≤560px. `.topbar-user` hidden ≤560px (name remains in Me page). Icon buttons 40px, gap 4px. `height:auto; min-height:64px` — no more painted overflow; the logout tap-target bug (unreliable clicks caused by overflowing paint order) disappears with it.
2. **Staff chip-nav ≤1023px:** the same sidebar links render as a horizontally scrollable chip strip (glass background, active chip = brand-soft pill) — every staff page reachable on phones with zero route/markup changes.
3. **Snapshot card ≤560px:** CTA drops to its own full-width line; ring + text keep readable widths. **Hero prompt ≤480px:** input and button stack full-width (bigger touch targets).

Desktop (>960px) and the ≥1024px sidebar are untouched — verified single-row topbar at 1280 and unchanged sidebar layout (regression checked).

## 3. Verification

| Gate | Result |
|---|---|
| prettier · tsc · build | clean / clean / ✅ `index-ncjoE9UB.js` |
| vitest | **126/126 green** (0 changed) |
| 360×800 student (dev + live Vercel) | topbar 2-row clean, search full-width, snapshot + hero correct, **zero console errors** |
| 360×800 teacher | chip-nav renders, tap → `/teacher/classes` navigates ✅ |
| 1280 / 768 regression | single-row topbar / wrap-mode as designed; sidebar column at ≥1024 unchanged |
| Live sync | local `web-preview` (healthy) **and** Vercel serve the same `index-ncjoE9UB.js`; `/api/health` 200 |

Evidence: `docs/uiux_renovation_evidence/mobile-audit/{before,after}/` (before: broken topbar + squeezed snapshot; after: fixed home, snapshot, teacher chip-nav — dev + live Vercel).

## 4. Pipeline (SOP)

- Commits: `2efd47e` (fix, release 0.9.1), `89a5bc5` (`.vercel` + `.env*` gitignore — closes an accidental-secret-commit risk introduced by `vercel link`)
- CI on both commits: Repository Sanity ✅ · Eval gate ✅ · API CI **6/6** ✅
- Release `v0.9.1` (tag push, no queue issue this time): GHCR images published — `api:v0.9.1` @ `sha256:fc986f1a…`, `web:v0.9.1`; SSH deploy skipped by design (`DEPLOY_ENABLED` unset)
- Deployed: local `web-preview` recreated on `bangla-gpt-web:v0.9.1` + **Vercel prod redeployed** (26s) — both serve the fixed bundle; version bump 0.9.0 → 0.9.1

## 5. Remaining note

The topbar fix is pure CSS — when the app eventually gets a dedicated mobile app shell (Capacitor build exists), revisit the topbar to possibly hide the search row behind an icon; current behaviour (full-width search row) is the standard mobile pattern and tests well.
