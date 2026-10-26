# Mobile distribution

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

The sync step is the one that decays silently: `android/app/src/main/assets/public`
is gitignored, so a stale copy looks exactly like a fresh one until a device
tests it. Two CI paths now cover that. On any PR that touches `apps/web/**`,
`android-release.yml`'s `debug-assemble` job builds the bundle, syncs it,
**hashes it against `dist/`** and assembles a debug APK — so "the Android shell
builds from this codebase" is a gate, not a hope. On a `v*` tag the same
workflow produces the signed `.aab` + release `.apk`; the Play Store runbook is
[docs/playstore/LAUNCH.md](playstore/LAUNCH.md).

Backend CORS: add the WebView origins — `capacitor://localhost` (iOS) and
`https://localhost` (Android) — to `ALLOWED_ORIGINS` on the API before
shipping the APK. Without them the APK's login calls fail CORS preflight
(the app now surfaces this as a dedicated configuration error instead of
a generic network failure). The API must also be reachable at a STABLE
origin: the current Cloudflare quick-tunnel hostname rotates and kills
both web and APK logins when it dies — promote a named tunnel or a
VM/PaaS domain and point both `API_ORIGIN` (Vercel) and `VITE_API_BASE`
(APK build) at it. A rotated origin strands every installed APK, because the
base is baked at build time; the rebuild is the only repair (docs/runbook.md,
"API origin down").

### Built in CI; what is still human

The Android build runs on GitHub's runners (JDK 17 + the preinstalled Android
SDK), so it no longer needs a workstation: see `.github/workflows/android-release.yml`.
This machine has no JDK or Android SDK (`java` absent, `ANDROID_HOME` unset), so
no APK is produced locally — that is recorded, not faked, and CI is the build
path. What remains owner-side:

1. **Upload key** — create it once, store it outside the repo, set the four
   `ANDROID_*` repository secrets. Signing is fail-closed: a release task
   without credentials throws instead of producing a debug-signed artifact.
   Steps in [docs/playstore/LAUNCH.md](playstore/LAUNCH.md) §1.
2. **Play Console** — create the app, fill App content (data safety, content
   rating, privacy policy URL), upload the `.aab`, decide the rollout. The
   answers are pre-written in `docs/playstore/`.
3. **Icon artwork** — `android/app/src/main/res` still ships the Capacitor
   template mipmaps; feed it the same artwork as the PWA icons. The launcher
   label is done: `res/values-bn/strings.xml` carries "বাংলা GPT টিউটর" for
   Bengali locales, with the English fallback in `values/strings.xml`.

### 🖐 Push notifications (FCM) — intentionally not wired yet

Push requires human/external work: a Firebase console project,
`google-services.json` dropped into `android/app/`,
`@capacitor/push-notifications` + `@capacitor-firebase/messaging`
plugins, and a server-side send path (the API currently has no push
sender). The weekly parent digest and assignment reminders email today
(SMTP via `services/mailer.py`, gated by `SMTP_ENABLED`); push is an ADD-ON,
tracked as a 🖐 follow-up, not a
silent gap: no code claims FCM exists.

### iOS

Needs a macOS host (Xcode) — `npx cap add ios && npx cap sync ios &&
npx cap open ios`. Out of scope locally; 🖐.

## Status page note

Admin-visible release status lives in `GET /status` (public page, web route
`/status`) and the admin dashboard, not here.
