# bangla-gpt-web

The web client for **Bangla GPT APP** — a React 18 + Vite + TypeScript
single-page app for students (grades 1–12), teachers, parents, school
administrators and platform admins. Bangla-first, with an English toggle; a PWA
with offline chapter copies; wrapped by Capacitor for Android.

The product-level README, the operator quick start and the deployment guide are
at the [repository root](../../README.md) and in
[`deploy/DEPLOYMENT.md`](../../deploy/DEPLOYMENT.md). This file covers only
what is specific to this package.

## What it is

A static bundle served behind nginx (or Vercel; `vercel.json`) that talks to
the API in [`apps/api`](../api) through the `/api` prefix. It holds no server
logic: everything the browser can decide is UX, and everything that matters is
enforced by the API. The built bundle must set `VITE_API_BASE` when it is not
served next to the API (the mobile build does; see
[`docs/mobile_release.md`](../../docs/mobile_release.md)).

## Layout

```text
src/
  api.ts             the one HTTP client; auth token handling lives here
  i18n.ts            bn/en UI dictionary (checked against docs/i18n-glossary.md)
  AuthContext.tsx    session state; RequireAuth gate
  AppShell.tsx       navigation shell, notification bell, language toggle
  pages/             one module per screen (student/, teacher/, admin, ...)
  components/        shared UI (ui.tsx primitives, brand, dialogs, a11y)
  lib/               focused helpers: datetime.ts (naive-UTC parsing), digits.ts
                     (Bengali numerals), safeMarkdown.tsx, offlineStore.ts,
                     theme.ts, tts.ts, voice.ts, analytics.ts, ...
  test/              vitest + Testing Library suites
e2e/                 Playwright specs (smoke, axe, keyboard, perf, visual)
scripts/gen-icons.mjs  PWA icon generation (see note below)
deploy/nginx.conf    production static-server config
android/             Capacitor Android project (generated; edit src/, not here)
```

## Running it locally

```bash
npm ci                    # Node >= 24 < 25, npm >= 11 (package.json engines)
npm run dev               # vite dev server on :5173, proxies /api -> 127.0.0.1:8000
```

The API must be running for anything past the login screen (see
[`apps/api/README.md`](../api/README.md)). `vite preview` mirrors the dev
proxy, so a built bundle can log in locally too.

## Commands

| Command | What it does |
| --- | --- |
| `npm run dev` | Vite dev server with the `/api` proxy. |
| `npm run build` | `tsc` then `vite build` — the type check gates the build. |
| `npm test` | Vitest unit/component suite (`vitest run`). |
| `npm run lint` | ESLint (type-aware, `--max-warnings 0`). CI fails on warnings. |
| `npm run format:check` | Prettier check (`npm run format` writes). |
| `npx playwright test` | Browser e2e smoke; the config starts a seeded API and the built app itself (Chromium; WebKit/Firefox nightly). `E2E_PYTHON` selects the API interpreter. |
| `npm run audit:serve` | Starts the stack Lighthouse CI audits: seeded API (mock provider) plus `dist/` served with the production caching policy and the `/api` proxy; prints `audit stack ready`. |
| `npx size-limit` | Bundle-size budgets (config in `package.json`); needs a prior `npm run build`. |
| `npm run cap:sync` | Build and sync the Capacitor Android project. |

CI runs exactly these (`ci.yml`: web job; `e2e-smoke` job) plus
`npm audit --omit=dev`.

## Things a contributor will trip over

- **The API sends naive UTC timestamps.** Never pass one to `new Date(...)`
  directly — use `parseServerDate` from `lib/datetime.ts`, or users outside UTC
  see times off by their whole offset. The file explains the failure it fixes.
- **Numerals are locale-dependent.** Use `lib/digits.ts` (Bengali digits in
  Bangla, ASCII in English) rather than interpolating raw numbers into copy.
- **Both languages ship in one dictionary** (`i18n.ts`); a key added for one
  language without the other fails `scripts/check_i18n.py` in CI, and product
  terms must match `docs/i18n-glossary.md` (`scripts/check_glossary.py`).
- **Markdown from the model is untrusted.** Render it through
  `lib/safeMarkdown.tsx`; it exists to keep raw HTML and hostile URL schemes out
  of the chat renderer and the notes.
- **`android/` is generated** by `npx cap sync`; make changes in `src/` (or
  `capacitor.config.ts`) and re-sync.
- **`scripts/gen-icons.mjs` cannot run as-is**: it imports `@resvg/resvg-js`,
  which is not in `package.json` or `node_modules` (tracked as AUD-CD-08).
  Install the package (or replace the script) before regenerating icons.

## Licence

MIT. Third-party notices, including the bundled Noto Sans Bengali and Hind
Siliguri fonts, are in [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).
