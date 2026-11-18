# DEVICE_VERIFICATION_VC206 — Android edge-to-edge + hardware back button

**Status: BLOCKED — owner/device action required (physical verification)**
**Recorded:** 2026-11-18 · Branch `feat/mobile-platform-hardening` · Baseline `d24719a`

---

## A1. What "vc206" means (established, not invented)

- `android-release.yml:72` — `VERSION_CODE: ${{ inputs.version_code || vars.ANDROID_VERSION_CODE || github.run_number }}`; tag builds take no input, so **versionCode = CI run number**.
- Artifact naming (`.apk-latest/` contents): `bangla-gpt-0.14.0-vc205.apk`, `…-vc204.aab`, `…-vc183.apk` — `vc<N>` = the build whose versionCode is N.
- Therefore **vc206 = the verification cycle for versionCode 206** — the signed release APK (`android-release-206`) built by CI run #206 from `d24719a` (0.14.0), recorded as awaiting device verification since 2026-11-18. No repository doc defines a different meaning; this derivation is from the workflow source and the artifact directory.

## A2. Edge-to-edge ownership model (source-verified)

- `capacitor.config.ts:30` — `adjustMarginsForEdgeToEdge: "auto"`: on Android 15+/API 35 (this project's `targetSdkVersion = 35`, `android/variables.gradle:4`) the Capacitor bridge insets the WebView below the enforced system bars; the CSS `env(safe-area-inset-*)` rules serve the browser/PWA where the WebView reports 0 insets. One ownership model, no double-inset by construction.
- `index.html:7` — `viewport-fit=cover, interactive-widget=resizes-content`.
- **On-device confirmation is outstanding** (status-bar icon contrast in light/dark, cutout behaviour, gesture vs 3-button nav) — see matrix §A4.

## A3. Hardware back-button semantics — engineering fix landed this branch

**CONFIRMED defect at baseline** (`nativeBackButton.ts:52` before this change): a clean-state back press called `App.exitApp()` on *every* route — nested routes exited the app instead of navigating back.

**Implemented priority order** (module doc + `resolveBackAction()`, unit-tested in `src/test/nativeBackButton.test.ts`, 16/16 passing):

1. **Keyboard** — editable element focused → blur it (system-like: back closes the IME first).
2. **Topmost dismissible overlay** — `Modal`/`ConfirmDialog` register via `pushOverlay()` while open (`components/ui.tsx`); back dismisses the topmost.
3. **Resumable state** — `markDirty()` pages (quiz attempt, streaming tutor turn) get the shared bilingual confirm dialog; Cancel preserves exact state (unchanged E6 behaviour).
4. **In-app history** — AppShell feeds the route stack from React Router's own navigation type (`trackRoute(path, PUSH|REPLACE|POP)`); a back press walks `history.back()` **only when the stack proves the previous entry is in-app**.
5. **Exit** — only at the true root: clean, no overlay, single-entry stack.

Guardrails against the briefed failure modes: deep links/PWA cold starts seed a 1-entry stack (no blind `history.back()` into foreign history); `resetRoutes()` on shell mount prevents post-logout back into pre-logout routes; POP is recorded with the landed path; REPLACE rewrites the top; duplicate PUSH on the same path is ignored; overlay dismissal is LIFO; the listener stays native-only (inert in browser/PWA — unchanged).

## A4. Acceptance matrix — device rows BLOCKED

| Dimension | Cases | Status |
|---|---|---|
| Android version | API 35 (this build's target); API 36 if available | **BLOCKED** — no device/emulator on this machine |
| Screen | 320–360 dp narrow, 390–432 dp, one cutout device | **BLOCKED** |
| Navigation | Gesture + 3-button | **BLOCKED** |
| Theme | Light + dark (status-bar icon contrast) | **BLOCKED** |
| App state | Fresh launch, warm resume, cold relaunch, offline launch | **BLOCKED** |
| UI state | Student home, tutor streaming, active quiz, teacher table, modal, login | **BLOCKED** |
| Keyboard | Gboard bn/en, visible/hidden, submit transitions | **BLOCKED** |
| System UI | Insets, nav contrast, splash→WebView transition | **BLOCKED** |
| Back | Root exit, nested back, dirty cancel/confirm, modal dismiss, keyboard dismiss | **BLOCKED on device**; priority order unit-tested (16/16) |
| Lifecycle | Background/resume, process recreation, interrupted network | **BLOCKED** |

Every row requires the signed APK installed on a physical device by the owner. Screenshots/recordings must use synthetic accounts only.

## A5. APK build and reproducibility

- **Existing evidence:** signed release APK `android-release-206` (versionCode 206) built by CI run #206 from `d24719a` — predates this branch's back-button fix, so it verifies the *baseline* behaviour only.
- **This change requires a new APK** (versionCode 207+ via the next `android-release.yml` run) for the §A4 matrix.
- Local build impossible on this machine (no JDK/Gradle/ADB — `AGENTS.md` §13); the automated gate available here is the workflow's `debug-assemble` PR job, which syncs the current web bundle and assembles a debug APK on JDK 21.
- Owner steps after merge: trigger `android-release.yml` (or tag), `adb install -r <apk>`, run §A4, record results here. Never sign with a debug key; release signing stays in CI secrets.

## A6. Gate status

| Gate | Status |
|---|---|
| No content under system bars / no double inset | Source-verified single ownership model; **device confirmation BLOCKED** |
| Hardware back follows the priority order | **PASS (unit)** — 16/16 in `nativeBackButton.test.ts`; device PASS pending |
| Dirty cancel preserves state | Unchanged E6 behaviour; device PASS pending |
| No exit from nested routes with in-app history | **PASS (unit)**; device PASS pending |
| No browser/PWA regression | Listener remains native-only; full web suite run in Phase 6 |
| APK asset sync hash + CI debug assemble | Runs on the PR (CI job `debug-assemble`) |
