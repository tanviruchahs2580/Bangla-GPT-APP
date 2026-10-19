# Play Store launch runbook

What this document is: the exact, ordered list of steps between "the repo is
green" and "the app is live on Google Play", with every credential named and
every step marked as either **repo-side (already done)** or **owner-side (you
run it)**. Nothing here is executed by CI: the release workflow builds and
signs the bundle, and a human uploads it.

Companion documents:

| Document | What it holds |
|---|---|
| `docs/playstore/listing.md` | Store listing copy (bn-BD + en-US), screenshot manifest, ASO notes |
| `docs/playstore/data-safety.md` | Data safety form answers, each mapped to the code fact behind it |
| `docs/playstore/content-rating.md` | IARC questionnaire answers |
| `docs/compliance/provider-terms.md` | The provider-terms record: tier-by-tier data use, retention and the paid-tier requirement |
| `docs/mobile_release.md` | The mobile build overview (PWA + Capacitor), CORS prerequisites |
| `docs/LAUNCH_READINESS_CHECKLIST.md` | Product-side gates (legal/child-safety review, UAT with a school) |

## 0. Repo-side state (already in place)

- Capacitor 7 Android project at `apps/web/android` — `applicationId app.banglagpt.tutor`,
  `minSdk 23`, `compile/targetSdk 35`.
- Release **signing is fail-closed**: `apps/web/android/app/build.gradle` reads
  `keystore.properties` (gitignored) or the `ANDROID_*` environment variables,
  and a `bundleRelease`/`assembleRelease` task graph with no credentials throws
  instead of producing a debug-signed artifact.
- `versionName` comes from `apps/web/package.json` (itself pinned to
  `apps/api/pyproject.toml` by `scripts/check_version.py`); `versionCode` comes
  from `-PversionCode`.
- `.github/workflows/android-release.yml` builds a signed `.aab` + release
  `.apk` on a `v*` tag or manual dispatch and uploads them as artifacts.
- Launcher label is localized (`values-bn/strings.xml`); the English fallback
  stays `Bangla GPT Tutor`.
- Privacy policy and terms are in-app routes (`/privacy`, `/terms`) that render
  in both languages, including the child-data and AI-disclosure sections.

## 1. Owner-side: create the upload key (once, 10 minutes)

The keystore is the app's identity on Play. Losing it without Play App Signing
enabled means you cannot ship an update under the same listing.

```bash
keytool -genkeypair -v -keystore banglagpt-upload.jks -alias banglagpt \
    -keyalg RSA -keysize 4096 -validity 10000
```

1. Store the `.jks` **outside** the repository, in a password manager or an
   encrypted backup. It is gitignored (`*.jks`, `*.keystore`,
   `keystore.properties`) — keep it that way.
2. For local release builds: copy `apps/web/android/keystore.properties.example`
   to `apps/web/android/keystore.properties` and fill in the four values.
3. For CI: add the four repository secrets

   | Secret | Value |
   |---|---|
   | `ANDROID_KEYSTORE_BASE64` | `base64 -w0 banglagpt-upload.jks` |
   | `ANDROID_KEYSTORE_PASSWORD` | keystore password |
   | `ANDROID_KEY_ALIAS` | `banglagpt` (or your alias) |
   | `ANDROID_KEY_PASSWORD` | key password |

4. Prefer **Play App Signing** (default for new apps): Google holds the app
   signing key, your keystore becomes the *upload* key and can be rotated from
   the console if it leaks.

## 2. Owner-side: repository variable for the API origin

The Capacitor WebView origin is `capacitor://localhost`, so a relative API base
cannot work. Set an absolute HTTPS origin as the repository variable (or pass it
to the workflow dispatch input):

```text
VITE_API_BASE = https://api.<your-domain>/api


Two more requirements on the API side for the packaged app to work:

- `ALLOWED_ORIGINS` must include `capacitor://localhost` and `https://localhost`
  (the Android WebView origins) in addition to the web origin.
- The API must be reachable over TLS from the device (the WebView forbids
  mixed content: `allowMixedContent: false`).

## 3. Owner-side: Play Console setup (once)

1. Create the app: name from `listing.md`, default language **bn-BD**, app
   (not game), free.
2. Complete **App content** — every declaration, in this order:
   - Privacy policy URL: `https://<your-web-host>/privacy`
   - Data safety: answers in `docs/playstore/data-safety.md`
   - Content rating questionnaire: answers in `docs/playstore/content-rating.md`
   - Target audience: 13+ (the register flow is consent-gated and the product is
     aimed at classes 6–10; do **not** declare "Designed for Families" — the
     listing is not built for the Families policy's content requirements)
   - Ads: no ads
   - News app: no
   - Government app: no
   - COVID-19 contact tracing: no
   - Financial features: none
   - Health: no
   - Data deletion URL/route: the in-app account deletion flow (`/me` → delete
     account), plus the same privacy URL as the web deletion route
3. Content: upload `docs/playstore/assets/screenshots/*.jpg` (phone) and
   `feature-graphic.jpg`, the 512×512 icon from `apps/web/public/icon-512.png`.
4. Store settings: category **Education**, tags from `listing.md`, contact email
   (a real monitored address), website URL.
5. If your developer account is a new *personal* account, Play requires a closed
   testing phase before production access. The console states the current
   tester count and duration for your account — follow what it shows (it has
   changed over time); do not plan a launch date that assumes production access
   on day one.

## 4. Build the bundle

Either dispatch the workflow (Actions → "Android release (Play Store AAB)" →
Run workflow, pass `version_code`) or build locally:

```bash
cd apps/web
VITE_API_BASE=https://api.<your-domain>/api npm run build
npx cap sync android
cd android
./gradlew bundleRelease -PversionCode=2
# -> app/build/outputs/bundle/release/app-release.aab
```

Verify what you are about to upload:

```bash
keytool -printcert -jarfile app/build/outputs/bundle/release/app-release.aab   # signer
unzip -p app-release.aab base/manifest/AndroidManifest.xml | head             # sanity
```

## 5. Owner-side: rollout

1. Play Console → Production → Create release → upload the `.aab`.
2. Release notes: reuse the newest `CHANGELOG.md` entry, trimmed (Play rejects
   over-long release notes).
3. Roll out in stages (for example 10% → 50% → 100%), watching **Android
   vitals** and the API's error-rate dashboard.
4. If a release must be stopped: Play Console → halt rollout. The bundle is
   already built, so shipping the fix means a new `versionCode`.

## 6. What CI does **not** do, on purpose

- It does not publish to Play: the Play Developer API needs a service-account
  JSON with account-scoped permissions, which is an owner credential this repo
  deliberately does not ask for. If you later want automated uploads, add the
  service account as a secret and a publish step that uploads the same artifact.
- It does not generate listing assets on every run: `STORE_ASSETS=1 npx
  playwright test e2e/store-listing.spec.ts` writes them, they are reviewed, and
  the reviewed copies are committed (a listing that silently re-renders itself
  is a listing nobody proofread).

## 7. Pre-flight checklist

- [ ] CI green on the commit you are shipping (all required checks).
- [ ] `VITE_API_BASE` set and the API answers `GET /api/health` over TLS.
- [ ] `ALLOWED_ORIGINS` includes the Capacitor origins.
- [ ] Upload key created, backed up, and (preferably) Play App Signing enabled.
- [ ] Data safety, content rating, target audience and ads declarations saved.
- [ ] Privacy policy reachable from a device browser (the URL in step 3).
- [ ] Screenshots show the current UI (re-capture if the UI changed since).
- [ ] Account deletion path verified from the app (Play enforces it for all apps
      with accounts).
- [ ] `docs/LAUNCH_READINESS_CHECKLIST.md` owner gates resolved (child-safety
      copy review, UAT school, production deployment).
