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

Backend CORS: add the WebView origins — `capacitor://localhost` (iOS) and
`https://localhost` (Android) — to `ALLOWED_ORIGINS` on the API before
shipping the APK. Without them the APK's login calls fail CORS preflight
(the app now surfaces this as a dedicated configuration error instead of
a generic network failure). The API must also be reachable at a STABLE
origin: the current Cloudflare quick-tunnel hostname rotates and kills
both web and APK logins when it dies — promote a named tunnel or a
VM/PaaS domain and point both `API_ORIGIN` (Vercel) and `VITE_API_BASE`
(APK build) at it.

### Signing and Play Store packaging (owner credentials)

Release signing is now fail-closed in `apps/web/android/app/build.gradle`: the
build reads `apps/web/android/keystore.properties` (gitignored, template at
`keystore.properties.example`) or the `ANDROID_*` environment variables, and
refuses to produce a release artifact without them (a debug-signed upload is
rejected by Play anyway, and a stopped build is cheaper than a rejected one).
`versionName` follows the web package version; `versionCode` comes from
`-PversionCode` and must increase on every upload.

```bash
cd apps/web
VITE_API_BASE=https://api.YOUR-DOMAIN/api npm run build
npx cap sync android
cd android && ./gradlew bundleRelease -PversionCode=2   # -> app-release.aab
```

CI builds the same artifact via `.github/workflows/android-release.yml`
(tag `v*` or manual dispatch, signing secrets as repository secrets), and
uploads the `.aab` + release `.apk`. The step-by-step owner runbook —
Play Console setup, data safety, content rating, store listing copy, staged
rollout — is **`docs/playstore/LAUNCH.md`**.

This machine has no JDK or Android SDK (`java` absent, `ANDROID_HOME`
unset), so no APK/AAB is produced locally — deliberately not faked; the CI
job is where the artifact comes from.

### App icon/label localization

Done in the repo: the launcher label is Bengali via
`android/app/src/main/res/values-bn/strings.xml` (`বাংলা GPT টিউটর`) with the
English fallback in `values/strings.xml`, and the mipmap icon set is committed
(adaptive icon + per-density mipmaps, same artwork as the PWA icons).

### Push notifications (FCM) — intentionally not wired yet

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
