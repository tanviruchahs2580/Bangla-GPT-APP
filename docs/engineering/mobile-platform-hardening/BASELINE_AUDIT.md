# BASELINE_AUDIT — mobile-platform-hardening workstream

**Workstream:** vc206 device verification + E5 typography Phase 2 + native system UI/assets + ResponsiveTable + DPIA + Cloudflare Workers feasibility
**Recorded:** 2026-11-18
**Baseline HEAD:** `d24719a2664bc204b0536fdb6357043793d7b4d0` (main, "Merge pull request #143 … feat/native-back-button")
**Working branch:** `feat/mobile-platform-hardening` (cut from the baseline; no user work in the tree — `git status --short` clean at cut time)

---

## 1. Repository and runtime state

| Item | Value (measured) |
|---|---|
| Branch / HEAD at recon | `main` @ `d24719a`, clean tree |
| Remote | `https://github.com/tanviruchahs2580/Bangla-GPT-APP.git` |
| Node / npm | v24.19.0 / 11.17.0 (matches `.nvmrc` = 24, `engines` ≥24 <25) |
| Python | 3.12.10 (CI runs 3.11 + 3.12) |
| Capacitor core/android/cli | **7.6.10** (`node_modules/@capacitor/*/package.json`) |
| `@capacitor/app` | ^7.1.2 |
| Android SDK levels | `minSdk 23`, `compileSdk 35`, `targetSdk 35` (`android/variables.gradle`) |
| CI Android toolchain | Temurin **JDK 21**, `./gradlew` (`android-release.yml` lines ~106–147, ~200) |
| Local Android toolchain | **absent** — no `java`, `gradle`, or `adb` on this machine (`which` empty). Android builds are CI-only per `AGENTS.md` §13. |

Worktree conflicts: none. No uncommitted user work was present.

## 2. Edge-to-edge geometry (current state)

- `apps/web/capacitor.config.ts:30` — `android.adjustMarginsForEdgeToEdge: "auto"`, with a comment recording the 2026-11-17 user report (status bar overlaid the header on targetSdk 35) and the chosen ownership model: the **bridge insets the WebView below the system bars where edge-to-edge is enforced**; the stylesheet's `env(safe-area-inset-*)` rules remain for browser/PWA surfaces where the WebView reports 0 insets.
- `apps/web/index.html:7` — `viewport-fit=cover, interactive-widget=resizes-content`.
- `src/styles.css` carries the safe-area rules for browser/PWA. **Single ownership model, no double-inset by construction** — but the resolved Capacitor 7.6.10 implementation of `auto` and the on-device result are exactly what vc206 must verify on hardware; that cannot be proven from source on this machine.
- Status-bar icon contrast: currently unmanaged (no `@capacitor/status-bar` plugin installed; theme-color meta tags only). Light/dark theme parity for system-bar icons is unverified on device.

## 3. Hardware back-button (current state) — CONFIRMED gap

`src/lib/nativeBackButton.ts` (E6, merged in #143):

- Dirty-state registry (`markDirty`) + a native-only `backButton` listener. When **any** page declared dirty state: one press opens the shared `ConfirmDialog` (`AppShell.tsx:292–303`, copy `backTitle/backBody/backLeave/backStay` in both languages, asserted by `src/test/nativeBackButton.test.ts`).
- **When nothing is dirty the handler calls `App.exitApp()` unconditionally** (`nativeBackButton.ts:52`) — i.e. a back press on *any* nested route exits the app. This is the exact defect the workstream brief calls unacceptable: in-app route history is never consulted.
- No overlay/modal dismissal step: `Modal`/`ConfirmDialog` (`components/ui.tsx:208, 344`) handle Escape but the hardware back does not dismiss them.
- No keyboard-first step: an open IME does not get first claim on the back press.
- No listener-registration race handling beyond the `then()` cleanup in `AppShell.tsx:122–128`.

Existing tests: `src/test/nativeBackButton.test.ts` (registry semantics, native-only no-op, wiring greps). Pages declaring dirty state: `QuizPage.tsx` (`markDirty("quiz")`), `AITutorPage.tsx` (`markDirty("tutor")`).

## 4. Fonts (current state)

- Imports in `src/main.tsx:14–18`: `@fontsource/noto-sans-bengali` 400/600/700 + `@fontsource/hind-siliguri` 400/600. **No `@font-face` rules exist in `styles.css`** — the entire web font pipeline comes from those package CSS files (each weight CSS declares bengali + latin + latin-ext subsets with `unicode-range`, woff2+woff sources, `font-display: swap`).
- `--font` (`styles.css:126`): `"Noto Sans Bengali", "Hind Siliguri", …` — Noto Sans Bengali is the primary face.
- Installed package contents (measured): `@fontsource/noto-sans-bengali` 1.5 MB, `@fontsource/hind-siliguri` 958 KB (all weights/subsets/formats). Per-file: noto bengali-400 woff2 = 44,352 B; noto bengali-600 = 47,636 B; noto bengali-700 = 47,788 B.
- `docs/capacity_plan.md` (historical, 2026-10): 12 woff2 subsets shipped = 317,008 B directory; honest Bengali cold-transfer ≈ 175 KB; decision recorded then: keep `@fontsource` for the pilot. **These are historical numbers; Phase 2 re-measures at current HEAD.**
- Licences: both packages SIL OFL 1.1 (`node_modules/@fontsource/*/LICENSE`). `THIRD_PARTY_NOTICES.md` already records both packages and the API-side bundled fonts.
- Service worker (`public/sw.js`): app-shell cache-first; **API responses never cached**; fonts get their own cache cap (`MAX_FONT_ENTRIES`) with FIFO eviction across deploys.
- No preload tags for fonts in `index.html`. No metric-matched fallback `@font-face` exists.

## 5. Native assets (current state)

- PWA: `public/icon.svg` (any), `public/icon-maskable.svg` (maskable, mark scaled to 75% into the safe zone), `public/icon-192.png` + `icon-512.png` (any). Manifest declares SVG any + SVG maskable + PNG 192/512 **any** — there is **no PNG `purpose: maskable`** entry (SVG-only maskable support is inconsistent across launchers).
- `apple-touch-icon` → `/icon-192.png` (real PNG, FE-12 fix). Favicon → `/icon.svg`.
- Android `mipmap-*`: `mipmap-xxxhdpi/ic_launcher.png` is **byte-identical (MD5 162052232af9…) to `public/icon-192.png`** — the brand mark was already propagated to at least xxxhdpi; other densities differ (need per-density regeneration check). `ic_launcher_foreground.png` at xxxhdpi = 66,505 B (provenance unverified).
- `mipmap-anydpi-v26/ic_launcher.xml`: background = `@color/ic_launcher_background` = **`#FFFFFF`** — the adaptive background is white while the brand mark is a dark-green gradient rounded square; a full-square brand PNG as adaptive foreground over white is not the approved mark treatment.
- Splash: `values/styles.xml` `AppTheme.NoActionBarLaunch` parent `Theme.SplashScreen`, background `@drawable/splash`; `drawable/`, `drawable-port-*`, `drawable-land-*` hold `splash.png` files (4–17 KB) — **visually unverified**, likely Capacitor template. No `@capacitor/splash-screen` or `@capacitor/status-bar` plugin installed.
- Plugin availability (npm registry, checked 2026-11-18): `@capacitor/status-bar@7.0.6`, `@capacitor/splash-screen@7.0.5` — compatible 7.x majors exist.

## 6. Data-table surfaces

Full inventory delegated to `TABLE_INVENTORY.md` (reconnaissance agent ran over `apps/web/src`); the E3 elevation wave already introduced shared table CSS and a `.cardable` card fallback. Migration decisions per surface are recorded there.

## 7. Privacy / DPIA / deployment (current state)

- **No DPIA exists** (`AGENTS.md` §15 "Known gaps"). Existing governance docs: `docs/data_minimization.md`, `docs/dpa_template.md`, `docs/security/threat-model.md`, `docs/ai/risk-register.md`, `docs/ai/system-card.md`, `docs/playstore/data-safety.md`.
- `docs/dpa_template.md` premise that Bangladesh has no comprehensive data-protection law is **stale** — the Personal Data Protection Act, 2026 (Act No. 63 of 2026, published 10 April 2026) exists on bdlaws.minlaw.gov.bd (act-1692). To be verified against the primary source in the DPIA workstream.
- Consent is versioned (`CONSENT_VERSION = "2026-09-v2"`, `consent_ip/at/version` fields — `AGENTS.md` §6). Retention windows: `answer_log` 730d, `ai_usage` 365d, `ai_jobs` 30d, token grace 30d. PII egress redaction in `services/pii.py`. Export/erasure in `services/gdpr.py`. Audit log append-only with five privileged event types.
- Live topology (memory + `docs/runbook.md` §7.1/7.3): hand-run Docker container `api-live` on the dev workstation, **SQLite** in production (`DATABASE_URL=sqlite:////data/app.db`), Cloudflare quick tunnel rotating, Vercel serving the web edge; rollback container `api-live-pre-0130` retained. Signed vc206 APK `android-release-206` was built from `d24719a` and awaits physical-device verification.
- Data-flow/vendor evidence for the DPIA is being collected from source (models, services, providers, compose) — see `docs/privacy/DPIA_BANGLA_GPT_DRAFT.md` evidence appendix when written.

## 8. Baseline test/build status

- Web gates at baseline (to be re-run after each phase): `npm run lint`, `npm run test` (vitest via `check_vitest_ran.mjs`), `npm run deadcode` (knip), `npm run build`, Playwright e2e (3 engines in CI; local runs need the port/API caveats in AGENTS.md §3).
- API gates: not touched by this workstream unless a defect is found in API code (document-only + web/native scope).
- CI: `android-release.yml` runs a `debug-assemble` PR gate that syncs the current web bundle and assembles a debug APK — this is the only APK path available from this machine.
- Known pre-existing red: the Workers Builds Cloudflare check (per prior session record, non-required).

## 9. Constraints carried into implementation

- No local Android build/device → physical-device verification is **BLOCKED — owner/device action required**; emulator evidence also unavailable locally. All other workstreams proceed.
- Capacitor plugins must be 7.x. No Tailwind/second state library. No API behaviour change. No consent/retention/audit-policy change. No baseline regeneration. Fonts: no third-party runtime font CDN; licence files preserved.
- `CHANGELOG.md` is single-writer (Principal Architect role) and regenerated via the documented process, not hand-edited ad hoc.
