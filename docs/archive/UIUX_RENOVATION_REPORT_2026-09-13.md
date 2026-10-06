# UI/UX World-Class Renovation — Final Report (RENO pass)

**Date:** 2026-09-13 · **Scope:** `apps/web` frontend only · **Base:** v0.7.0 + uncommitted WP-DR redesign
**Directives honored:** no git commit/push/tag, no CI/CD trigger, `apps/api` byte-untouched, features & content unchanged, R5/R6/R12 respected (protected tokens/font/prompts intact; test count only grew).

---

## 1. Current-condition review (before this pass)

**What was already good** (kept): v3 "Bangladesh green" token system with fluid Bengali-safe type, glass topbar + animated bottom-nav pill, WP-05 component primitives, WP-DR teacher IA split (6 pages) + student practice hub, 235 aria-* usages, dark-mode token parity, prefers-reduced-motion kill-switch, 115-test suite green.

**Defects found & upgraded:**

| # | Area | Defect | Fix |
|---|------|--------|-----|
| 1 | `styles.css:2706` | Broken comment block — `*/` inside `.btn-*/` closed the comment early; parser garbage consumed the `.page-title` rule | Comment repaired, rule restored |
| 2 | Tokens | 3 overlapping elevation sets (`--elev-*`, `--shadow-sm/md/lg`, `--shadow-1/2/3`) | One canonical `--elev-*` scale; legacy names are aliases |
| 3 | Breakpoints | Stray `768px` beside the `760px` step | Unified to 480/560/760/1024 |
| 4 | Primitives | No Modal/Skeleton/Field/Tabs/Avatar; hand-rolled dialog in AITutorPage | New primitives in `ui.tsx` (Modal = portal + focus trap + Esc + scroll lock + focus restore) |
| 5 | Locale switch | `navigate(0)` full page reload (AppShell, MePage ×2, TeacherProfilePage) | `LangRoot` in-place remount — instant, no network, PWA-safe; dark-mode toggle likewise reload-free |
| 6 | Inline styles | ~150 `style={{}}` across 18 files (MePage 44, create flows 32…) | ~145 eliminated via token utilities; remaining 5 are dynamic layout values (rings, reader font-scale) |
| 7 | Forms | Bare `<input>/<select>/<textarea>` (browser-default styled) in CreatePage flows + staff pages | Tokenized (`.input/.select/.textarea` + `Field`) |
| 8 | i18n | English toggle broken in ~12 files (hardcoded Bengali UI strings; raw API subject values like "science · শ্রেণি 6") | 40+ new keys, `tSubject()` helper, `errors.ts` flows through i18n |
| 9 | Nav | Legacy `.bnav-dot` double indicator under the WP-04 pill | Removed (pill only) |
| 10 | Tables | `table-scroll` vs `table-wrap` dual vocabulary (deferred WP known-issue) | 14 wrappers unified to `.table-wrap` + `table.data`; dead CSS deleted |
| 11 | Staff chrome | Parent/admin/school sidebar links icon-less, inconsistent with teacher nav | Same `side-link` pattern + icons (style-only, no new routes) |
| 12 | A11y | No automated sweep beyond Welcome page | `axeSweep.test.tsx` over 8 redesigned surfaces + Modal — 0 serious/critical |
| 13 | QA tooling | `python3` missing on Windows PATH | Local `.venv/Scripts/python3.exe` shim for `scripts/smoke.sh` (untracked tooling) |

## 2. Verification (developer gate)

| Gate | Result |
|---|---|
| `npx tsc` | clean |
| `prettier --check src` | clean |
| `vitest run` | **43 files / 126 tests green** (baseline 41/115; +11 tests, 0 regressions, 0 deletions) |
| `npm run build` | success (`dist/` final bundle `index-C4XU3Z_2.js`) |
| API (`apps/api`) | byte-untouched (`git status` shows no source diff) |

## 3. Verification (as a user, on the live stack)

- **API battery:** `scripts/smoke.sh` — all steps pass (health/ready/register/login/learn/tutor grounded/quiz start→submit→explain/me/export/delete). `scripts/e2e_user_journey.py` — **21/21 PASS**.
- **Browser journey (real clicks, 1280×800):** student register → login → home → AI tutor (Bangla question → SSE answer with supportive refusal + low-confidence hint + conversation persisted) → practice hub → learn → me; theme dark↔light and language bn↔en toggled **in place with zero reloads**; teacher register (conditional guardian-consent verified: hidden for teachers, shown for students) → all 6 teacher pages. **Zero console errors on every page.**
- **Live sync proof:** served bundle at `http://localhost:8081` **and** the public tunnel is byte-identical to the local final build (`assets/index-C4XU3Z_2.js` both places); `/health` 200; `/api` proxy 200 through both entry points; service worker safe (network-first navigations, hashed assets).
- **Evidence:** before/after screenshots in `docs/uiux_renovation_evidence/{before,after}/`.

## 4. Issues caught *during* live QA (fixed + re-gated + re-synced)

1. **Deploy-tooling:** Git Bash MSYS path mangling rewrote `--build-arg VITE_API_BASE=/api` → `C:/Program Files/Git/api`, baking a broken API base into the served bundle (login failed with `file://` fetch). Fixed with `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"`; re-verified end-to-end. *Lesson recorded: always use the guard on Windows docker builds.*
2. **Content:** student home rendered the raw API subject value ("science · শ্রেণি 6"); now localized via `tSubject()` ("বিজ্ঞান · শ্রেণি 6"). Re-ran the full gate (126/126) and re-synced live before final verification.
3. **Infra (pre-existing, not caused by this work):** the ephemeral trycloudflare tunnel had been dead since 01:42 ("Tunnel not found") — recreated; new URL **https://robert-giants-preceding-jelsoft.trycloudflare.com** (quick tunnels rotate on restart; a named tunnel would be stable).

## 5. Remaining recommendations (not done — out of scope / product decisions)

- Staff sub-routes for parent/admin/school (feature work; sidebar is now visually ready).
- Legal-page English body (content translation, product/legal decision).
- Promote the axe sweep + Lighthouse to CI (WP known-issue #1 — now the sweep exists as a permanent test file, so CI adoption is one workflow line).
- Named Cloudflare tunnel (or real hosting) for a stable public URL.
- Test accounts left on the local stack: `beforeqa_1789260126@example.com`, `renuqa_teacher@example.com` (password `StrongPass123!`) — local dev volume only.

**Final state: all parameters verified functional — unit, accessibility, build, API battery, live stack, and as-user browser journey. Live stack serves the exact final build.**
