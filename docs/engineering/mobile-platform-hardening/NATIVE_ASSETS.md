# NATIVE_ASSETS — status bar, splash screen, launcher icons

**Status:** engineering complete; on-device behaviour verification BLOCKED (no device/JDK on this machine — see DEVICE_VERIFICATION_VC206.md)
**Date:** 2026-11-18 · Branch `feat/mobile-platform-hardening`

---

## 1. Plugin decision (C1) — audited before installing

- Capacitor core/android/cli = **7.6.10**; installed `@capacitor/status-bar@7.0.6` and
  `@capacitor/splash-screen@7.0.5` — both **7.x majors, exact-pinned** (no Capacitor 8 majors
  pulled in). `npx cap sync android` registers 3 plugins and completes in <1 s.
- v7 behaviour verified against the official v7 docs (retrieved 2026-11-18): on Android 12+
  the **OS splash screen governs launch visuals** and most plugin options are ignored there;
  the plugin owns the post-system-splash window and the API < 31 compat path
  (`Theme.SplashScreen` + androidx core-splashscreen, already present in `styles.xml`).

## 2. Status bar (C2) — one ownership model, guarded calls

- `capacitor.config.ts` keeps `adjustMarginsForEdgeToEdge: "auto"` as the **single** inset
  owner. The new `src/lib/nativeSystemUi.ts` sets **only the icon style**, synced to the app
  theme (light → dark icons, dark → light icons) via the existing theme module.
- It never calls `setOverlaysWebView`/`setBackgroundColor` — no competing inset strategy.
- Guarded by `Capacitor.isNativePlatform()`; every rejection swallowed; **not awaited** in
  `main.tsx` so a cosmetic plugin failure cannot delay first paint. Browser/PWA: inert.

## 3. Splash screen (C3)

- Config: `launchAutoHide: true` + `launchShowDuration: 500` + `launchFadeOutDuration: 200`,
  `backgroundColor: "#f4f6fd"` (the app background), `CENTER_CROP`, no spinner.
- **No app-driven `hide()` is wired** — the auto-hide is the fail-safe, so a startup error
  (font preload, auth bootstrap, SW registration) can never trap the user on splash. No fake
  HTML splash overlay was added; font preload/auth/SW flows are untouched.
- **Defect fixed:** the launch drawables were the Capacitor template splash (blue Capacitor
  logo on white — verified visually at `drawable/splash.png`). All 11 `splash.png` drawables
  (portrait/land × 5 densities + default) are regenerated brand assets: `#f4f6fd` background,
  centred approved mark at 30% of the short side.

## 4. Icons (C4) — one source of truth, reproducible pipeline

`scripts/generate_native_assets.mjs` (committed; Playwright chromium rasteriser; same inputs
→ same PNGs) generates **31 assets** from `public/icon.svg` / `public/icon-maskable.svg` —
no new artwork, no stretching:

| Output | Source | Notes |
|---|---|---|
| `icon-192-maskable.png`, `icon-512-maskable.png` | `icon-maskable.svg` (mark pre-scaled into the safe zone) | full-bleed RGB; manifest gains two `purpose: "maskable"` PNG entries (SVG-only maskable support is launcher-inconsistent) |
| `mipmap-*/ic_launcher.png` + `ic_launcher_round.png` (48/72/96/144/192) | `icon.svg` | RGBA with **transparent corners** (the rounded square's own shape); verified alpha=0 at (0,0) |
| `mipmap-*/ic_launcher_foreground.png` (108/162/216/324/432) | mark-only derivation of `icon.svg` (background rect removed), scaled ×0.66 centred | adaptive safe zone = inner 66/108 dp; transparent elsewhere |
| `drawable/ic_launcher_background.xml` | brand gradient stops (#16a34a → #166534 → #052e16, angle 315°) | replaces the flat **white** adaptive background |
| splash drawables ×11 | mark + `#f4f6fd` | replaces the Capacitor template |

**Defect fixed:** the adaptive icon previously used the full rounded-square brand PNG as the
foreground over a white `@color/ic_launcher_background` — launchers would crop the rounded
corners and show white slivers. Now: gradient background layer + mark-only foreground inside
the safe zone. The obsolete `values/ic_launcher_background.xml` colour was removed (no
remaining references — verified by grep).

The Android manifest is untouched (`android:icon="@mipmap/ic_launcher"`; no `roundIcon`
reference exists, so none was invented). Favicons/apple-touch-icon references unchanged.

## 5. Gates (C5)

| Gate | Status |
|---|---|
| `npx cap sync android` succeeds, generated references resolve | PASS (3 plugins; splash/status-bar registered) |
| Clean-checkout Android debug build | **CI-only** — the PR's `debug-assemble` job runs it (no JDK here) |
| No AAPT2/Gradle resource errors | expected from the regenerated resources; confirmed by CI, not locally |
| PWA manifest icons correct dimensions/purpose | PASS — verified in built `dist/manifest.webmanifest` |
| Launcher icons no longer generic templates | PASS — brand-derived (was already partly true at xxxhdpi; now all densities + foreground + splash) |
| Splash/status-bar behaviour on the device matrix | **BLOCKED — owner/device action required** |
| Native plugins harmless in browser/PWA | PASS by construction (native-only guards); full web suite green |
| Asset generation reproducible + documented | PASS — committed script; `node scripts/generate_native_assets.mjs` |

## 6. Cross-workstream checks

- The synced native bundle (`android/app/src/main/assets/public/`) contains the self-hosted
  fonts and the new maskable PNGs — the APK serves fonts from the packaged bundle (no remote
  font host), satisfying the integration requirement with Workstream B.
- One brand palette throughout: `#f4f6fd` background, `#166534` theme green, the approved
  mark — PWA and native now match.
