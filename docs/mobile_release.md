# Mobile distribution (S5.9)

Two supported paths, in order of preference for schools with cheap phones:

## 1. PWA (zero download — works today)

The web app is a full PWA: `public/manifest.webmanifest` (standalone,
theme `#4353b8`, Bengali name, 192/512 + maskable icons) and `public/sw.js`
(app-shell cache-first, navigations network-first with offline fallback,
**API responses are never cached** — child data must not sit in a shared
device's cache). Chrome on Android shows "Add to Home screen"; iOS Safari
shows "Add to Home Screen" (service worker gives offline shell, not
push). The service worker registers in production builds only
(`import.meta.env.PROD` gate in main.tsx).

Verification: `npm run build` then check `dist/` contains
`manifest.webmanifest`, `sw.js`, `theme-boot.js`, icons — all present in
this repo's build; Lighthouse PWA audit is a 🖐 human step on real phones.

## 2. Native Android wrapper (Capacitor 7)

Config: `apps/web/capacitor.config.ts` (`app.banglagpt.tutor`,
webDir `dist`, mixed content disabled). Android project scaffolded at
`apps/web/android/` (committed project files; `android/.gitignore` covers
build outputs).

Workflow (every release):

```bash
cd apps/web
# Release builds MUST point the WebView at the real API, because the
# WebView origin (capacitor://localhost) cannot use the relative '/api':
VITE_API_BASE=https://api.YOUR-DOMAIN/api npm run build
npx cap sync android          # copies dist into the native project
```

Backend CORS: add the WebView origins — `capacitor://localhost` (iOS) and
`https://localhost` (Android) — to `ALLOWED_ORIGINS` on the API before
shipping the APK.

### 🖐 Human build/signing steps (NOT possible in this environment)

This machine has no JDK or Android SDK (`java` absent, `ANDROID_HOME`
unset), so no APK was produced — deliberately not faked. On a build
machine:

1. Install JDK 21 + Android Studio (SDK 35). `cd apps/web/android &&
   ./gradlew assembleDebug` for a test APK.
2. Release signing: create a keystore (store it OUTSIDE the repo, never
   in git/CI logs), set `keystore.properties` (git-ignored), then
   `./gradlew assembleRelease` / `bundleRelease`. Play Store prefers
   Play App Signing.
3. App icon/label localization: replace `app_name` string with the
   Bengali name "বাংলা GPT টিউটর" and feed `android/app/src/main/res`
   mipmap icons (same artwork as the PWA icons).

### 🖐 Push notifications (FCM) — intentionally not wired yet

Push requires human/external work: a Firebase console project,
`google-services.json` dropped into `android/app/`,
`@capacitor/push-notifications` + `@capacitor-firebase/messaging`
plugins, and a server-side send path (the API currently has no push
sender). The weekly parent digest and assignment reminders email today
(mailer, S5.4); push is an ADD-ON, tracked as a 🖐 follow-up, not a
silent gap: no code claims FCM exists.

### iOS

Needs a macOS host (Xcode) — `npx cap add ios && npx cap sync ios &&
npx cap open ios`. Out of scope locally; 🖐.

## Status page note

Admin-visible release status lives in S5.10 (`/status` + admin status
page), not here.
