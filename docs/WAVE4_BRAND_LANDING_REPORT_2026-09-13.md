# WAVE-4 — National-Scale Brand & Landing Renovation — Final Report

**Date:** 2026-09-13 · **Scope:** `apps/web` frontend only (visual/brand layer)
**Directives honored:** no git commit/push/tag, no CI/CD trigger, `apps/api` byte-untouched, zero feature/logic changes, all 126 existing tests kept green.

---

## 1. What was asked

1. Background is boring/plain on every page → design an ambient, national-scale background system.
2. Logo is not "national scale" → redesign the brand mark.
3. Redesign the landing page to world-class, launch-worthy quality for a national rollout.
4. No changes to existing features · no push/commit/CI-CD · test the live version for sync · test every function as a user · final report.

## 2. Design rationale (scale · goal · user)

The product is an NCTB-textbook-grounded, Bangla-first AI tutor platform for Bangladesh
(students, teachers, parents, school admins). The brand identity therefore draws on:

- **শাপলা (water lily)** — Bangladesh's national flower, rising from an open book
  (the NCTB textbook) — "knowledge blooming from the national curriculum".
- **Bangladesh-green gradient badge** kept consistent with the existing design tokens
  (`#16a34a → #166534 → #052e16`) and the golden accent already used in the app.
- A **learning spark** for the AI dimension (replaces the old graduation-cap glyph).
- Font-free geometry: the old mark (and favicon) depended on `<text>` + system Bengali
  fonts; the new mark is pure vector paths, so it renders identically at 16 px favicon,
  in-app, and 512 px store icon, in every browser/OS.

## 3. Changes delivered

| # | Area | Files | Detail |
|---|------|-------|--------|
| 1 | **Logo — "Shapla Book" mark** | `src/components/BrandMark.tsx`, `public/icon.svg`, `public/icon-maskable.svg` | New 5-petal golden shapla rising from a white open book + spark on the brand-gradient badge; ~2 KB inline; no font dependency; maskable variant scaled to the 80 % safe zone |
| 2 | **Raster icons regenerated** | `public/icon-192.png`, `public/icon-512.png`, Android `mipmap-*` launchers + foregrounds | Via new tooling `apps/web/scripts/gen-icons.mjs` (`@resvg/resvg-js`, installed `--no-save`, `package.json` untouched). Android res PNGs are gitignored per Capacitor convention |
| 3 | **Ambient background system (every page)** | `src/styles.css` (`body::before`, `body::after`) | Fixed viewport layer: brand-mesh radial glows (brand / AI-indigo / sky) + nakshi-kantha-inspired 45° stitch weave fading out toward mid-page. Pure CSS (zero image weight), token-driven (automatic dark-mode parity), `pointer-events:none`, sits behind all content |
| 4 | **Splash/auth aurora** | `.splash::before/::after` | Slow drifting aurora glow + shapla-light arc on public pages; disabled by the existing global `prefers-reduced-motion` guard |
| 5 | **Landing redesign (WelcomePage)** | `src/pages/WelcomePage.tsx` | Kicker chip → 96 px mark → national-scale headline/value-prop → both CTAs (unchanged tracking `welcome_cta`) → trust row → 4-card feature grid (AI tutor / practice / library / teacher copilot) → stat strip (শ্রেণি ৬–১০ · ৫ ভূমিকা · ১০০% বাংলা) → tagline footer. All content bilingual via i18n |
| 6 | **Split auth layout (Login/Register)** | `src/pages/LoginPage.tsx`, `src/pages/RegisterPage.tsx` | Brand panel (mark, kicker, name, tagline, trust list, roles note) + the untouched form card on the right (≥900 px split; stacks compactly on mobile). Every form attribute, id, label, autocomplete, error path and handler is byte-identical |
| 7 | **Student hero flourish** | `.hero::before` | Warm golden shapla-glow arc on the home hero (previously flat green) |
| 8 | **i18n** | `src/i18n.ts` | 21 new keys (bn + en): `landingKicker`, `landingHeroTitle/Sub`, 4× feature title/sub, feature/stats labels, 3× stat value/label, `authBrandNote` |

**Not touched:** routes, API layer (`src/api.ts`), auth logic, quiz/tutor/learn logic, teacher/parent/admin/school pages' behaviour, design tokens, fonts, `index.html` metadata, PWA manifest semantics, service worker.

## 4. Verification — developer gates

| Gate | Result |
|---|---|
| `npx tsc --noEmit` | clean (before **and** after) |
| `prettier --check src` | clean |
| `vitest run` | **43 files / 126 tests green** — identical to baseline, 0 deleted; includes the axe-core WCAG sweep on WelcomePage and 8 app surfaces |
| `npm run build` (tsc + vite) | success → bundle `assets/index-o7564-N7.js` |
| `apps/api` diff | **0 files changed** |
| `apps/web/package.json` diff | **0 lines** (resvg installed `--no-save`) |

## 5. Verification — as a user, on the live stack

Live stack = `web-preview` docker container (nginx, port 8081, network `bgpt-live`) + API `api-live` (untouched) + public Cloudflare tunnel.

**Deploy/sync procedure (no CI/CD):** `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"` docker build of `bangla-gpt-web:v0.8.1-wave4` (Windows MSYS path-guard), old `web-preview` removed, new container recreated with identical config (network, port, restart policy). Old image `bangla-gpt-web:v0.8.1` retained for instant rollback.

| Check | Result |
|---|---|
| `http://localhost:8081/` serves final build | 200, `assets/index-o7564-N7.js` (hash identical to local build) |
| Public tunnel `https://eos-employ-advertising-voip.trycloudflare.com` | 200, **same** `index-o7564-N7.js` → live is in sync with the final version |
| `/api/health` through web proxy (local + tunnel) | 200 |
| Register student (fresh `wave4_1789289768166@example.com`) | success → auto-login → `/student` |
| Landing (light + dark, bn + en, desktop + 375 px mobile) | verified visually; new mark, aurora, mesh, feature grid, stats all render |
| AI tutor (question from hero prompt) | navigates to tutor, grounded answer streams, evidence chips + confidence + strategy chips + feedback buttons all work |
| Practice → 5-question quiz → submit | flow + result review + explain buttons work; streak updated to 1 day |
| Learn page (subjects/classes) + Me page (profile, heatmap) | functional |
| Theme toggle light↔dark, language toggle bn↔en | instant, in place, both directions verified |
| Wrong-password error path | friendly localized alert shown |
| Logout → public landing | works on live |
| Console errors across the whole journey | **zero** |

**Before/after evidence:** `docs/uiux_renovation_evidence/wave4/{before,after}/`
(before: old student home + old welcome @8081; after: new welcome light top/bottom, mobile welcome/login, dark-mode Me, live login EN dark, tunnel landing, new tutor page).

## 6. Issues caught during the pass

1. **Port 5173 is occupied by a different project** (a farmer-AI app, not this repo). A separate dev server was run on **5174** for dev inspection and stopped afterwards. *Lesson recorded: never assume :5173 is this app on this machine.*
2. `src/test/welcome.test.tsx` asserts the tagline renders on WelcomePage — the redesigned landing keeps `welcomeTagline` as the closing brand line, satisfying the existing contract **without editing the test**.
3. Full-page screenshots show duplicated hero content when `position:fixed` ambient layers are stitched by the capture tool — verified to be a screenshot artifact, not a page defect (viewport + scrolled captures are correct).
4. Pre-existing (out of scope, untouched): Learn page subject button shows the raw API subject value in one spot ("science শ্রেণি 6") — same class of issue the previous wave fixed on the home page.

## 7. Test accounts left on the local stack

- `wave4_1789289768166@example.com` / `StrongPass123!` (student, local dev volume only)

## 8. Rollback

`docker rm -f web-preview && docker run -d --name web-preview --network bgpt-live -p 8081:80 --restart unless-stopped bangla-gpt-web:v0.8.1` restores the previous live preview; working-tree changes are uncommitted and can be reverted with `git checkout -- apps/web` if ever needed.

## 9. Recommendations (not done — product decisions)

- Bump release version + commit when the owner is satisfied (deliberately not done).
- Named Cloudflare tunnel / real hosting for a stable public URL.
- Regenerate Android splash drawables (brand-aligned splash screens) in a future wave.
- Promote the axe sweep to CI (carried over from the previous wave).
