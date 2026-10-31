import { defineConfig, devices } from "@playwright/test";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Browser end-to-end suite (restored from a1929ad, rewired for this branch).
 *
 * Scope: one Chromium project driving the *real* web app against the *real*
 * API with the deterministic `mock` LLM provider. The role journeys live in
 * `e2e/smoke.spec.ts`; nothing here is mocked at the HTTP layer, so a broken
 * route, a broken auth guard or a broken proxy fails the suite. Firefox and
 * WebKit are deliberately NOT here: they run through
 * `playwright.engines.config.ts`, because their install cost does not belong
 * on every run.
 *
 * Run it:
 *   apps/web> npx playwright test            # dev server harness (default)
 *   apps/web> npm run test:e2e               # same, via package.json
 *
 * The suite starts both servers itself: a seeded API (uvicorn, port 8000)
 * and the web app on port 5173. Default harness is `npm run dev` (fast, no
 * build); `E2E_WEB=preview` swaps in `vite preview` of a production build on
 * port 5174, which is the only harness where the service worker exists --
 * offline-shell.spec.ts skips under the dev server for exactly that reason.
 * Set E2E_PYTHON when the API's dependencies live outside the repo venv.
 *
 * Determinism: no fixed sleeps anywhere -- assertions rely on Playwright's
 * auto-waiting; `trace`/`screenshot` fire on failure only; one worker,
 * because the journeys share seeded rows (the parent-link test consumes an
 * invite code).
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..");

// The interpreter that can `import bangla_gpt_api`. CI exports E2E_PYTHON
// (runner python + `pip install -e apps/api`); local default is the repo venv.
const PYTHON =
  process.env.E2E_PYTHON ??
  (process.platform === "win32" ? ".venv/Scripts/python.exe" : "python");

// One throwaway SQLite database per run, outside the repository: the seed
// script and the API must agree on it, and no run may inherit another's rows.
const DB_FILE = join(tmpdir(), `bgpt-e2e-${Date.now()}-${process.pid}.db`);
const DATABASE_URL = `sqlite:///${DB_FILE.replace(/\\/g, "/")}`;

const API_PORT = Number(process.env.E2E_API_PORT ?? 8000);
// Dev harness on 5173; the preview harness deliberately takes a different
// port so it can run beside an already-running dev server instead of being
// silently "reused" (reuseExistingServer) into testing the wrong bundle.
// E2E_WEB_PORT overrides both for machines where the default port belongs to
// another project's dev server (measured failure: the harness reused a
// foreign app on 5173 and axe swept the wrong product).
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? (process.env.E2E_WEB === "preview" ? 5174 : 5173));
const API_URL = `http://127.0.0.1:${API_PORT}`;
const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;

// Default wiring: the app calls `/api/*` and the Vite server proxies it to
// 127.0.0.1:8000 (vite.config.ts, dev and preview alike). When the API port
// is overridden the proxy target cannot follow, so the app is pointed
// straight at the API with VITE_API_BASE and the API's ALLOWED_ORIGINS
// admits the harness origin.
const DIRECT_API = API_PORT !== 8000;
const WEB_ORIGINS = `http://127.0.0.1:${WEB_PORT},http://localhost:${WEB_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  // Artifacts land under the paths .gitignore carries for Playwright
  // (.playwright-report/, test-results/); traces/screenshots on failure only.
  outputDir: "./test-results",
  // Generous because the whole app is a lazy-loaded module graph: the first
  // navigation of a run pays for the compile/loading of every route chunk.
  // The per-assertion default stays tight so a broken selector still fails fast.
  timeout: 120_000,
  expect: {
    timeout: 20_000,
    // One reviewed baseline set serves every runner -- the platform suffix is
    // dropped from the snapshot file name (snapshotPathTemplate below) and a
    // 2% pixel-ratio difference is tolerated so cross-platform text
    // rasterisation does not fail the review it is meant to support.
    // The matrix and the review note live in e2e/visual.spec.ts.
    toHaveScreenshot: {
      // 5%: measured run-to-run text-rasterisation variance on identical
      // commits is 3-5% on this suite (two consecutive runs on one machine
      // failed different 360/768 snapshots at 0.03-0.05 with no source
      // change). 2% false-failed every other run; a real layout breakage
      // (missing card, collapsed section) diffs at 10%+ and still fails.
      maxDiffPixelRatio: 0.05,
      animations: "disabled",
      caret: "hide",
    },
  },
  snapshotPathTemplate: "{testDir}/__screenshots__/{testFileName}/{arg}{ext}",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  // No retries, in CI or locally. A flake must be visible on its first
  // failure; a retry hides it and the audit counted the retry pattern itself
  // as the defect. The suite is green without them (recorded full runs).
  retries: 0,
  reporter: [
    ["list"],
    ["junit", { outputFile: ".playwright-report/junit.xml" }],
    ["html", { outputFolder: ".playwright-report/html", open: "never" }],
  ],
  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    // The app registers a service worker in production builds only; blocking
    // it keeps a stale cache from ever masking a regression.
    serviceWorkers: "block",
  },
  // FE-18 / F-158: the desktop project never runs the mobile-only spec, and
  // the mobile profile (one device: Pixel 5, 393x851) runs the mobile-only
  // spec plus the critical journey file at that viewport, so a route, auth
  // or layout break on a phone fails CI instead of shipping -- the budget
  // stays two files, not a second copy of the whole suite.
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      testIgnore: /mobile\.spec\.ts$/,
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 5"] },
      testMatch: /(mobile|smoke)\.spec\.ts$/,
    },
  ],
  webServer: [
    {
      // Seed first (roles cannot be self-registered through the product),
      // then serve. One shell so both processes inherit the same
      // DATABASE_URL. The long-history seed is what perf.spec.ts throttles;
      // it is idempotent and costs 120 inserts on a fresh database.
      command: `"${PYTHON}" apps/web/e2e/seed_e2e_users.py && "${PYTHON}" apps/web/e2e/seed_long_history.py && "${PYTHON}" -m uvicorn bangla_gpt_api.main:app --app-dir apps/api/src --host 127.0.0.1 --port ${API_PORT}`,
      cwd: REPO_ROOT,
      url: `${API_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        DATABASE_URL,
        // mock provider: no API key, no network, deterministic answers.
        ENV: "test",
        JWT_SECRET: "test-secret-0123456789abcdef0123456789",
        LLM_PROVIDER: "mock",
        // jobs run inline in-process; no Redis/ARQ is needed for the suite.
        JOBS_BACKEND: "inline",
        ALLOWED_ORIGINS: WEB_ORIGINS,
        SMTP_HOST: "",
        // Account provisioning stays a DB seed (seven fixed users reused by
        // every spec), so the only per-IP limiter the suite can trip is
        // /auth/login: every spec's signIn posts it from one address, and
        // the production 10/min bound would 429 the later specs while the
        // product itself stays fine. The per-field knob is the sanctioned
        // harness override (middleware_stack._PER_FIELD_ROUTES); the
        // limiter's own tests pin the production value.
        RATE_LIMIT_LOGIN_PER_MINUTE: "240",
        // The suite's own navigation rate must not be an input to the flows.
        // GET /users/me is bounded at 10/min per user in production (F-127,
        // the cheap half of that rule's destructive siblings); every spec
        // entry signs in and every page load probes the session, and the dev
        // harness mounts each component twice (StrictMode), so the flows
        // below legitimately exceed the bound and then every later request
        // answers 429. The production bound stays production's: the API's
        // own tests pin the rule (tests/test_rate_limit_coverage.py) and no
        // e2e spec asserts a 429 on the config-driven routes. What this
        // override does replace is the config-driven rule map for this
        // test-only process; the per-field knobs (login, tutor) are applied
        // by the API independently and stay in force.
        RATE_LIMIT_RULES: JSON.stringify({ "/users/me": [240, "user"] }),
        // The tutor conversation routes are one per-user bucket
        // (/tutor/conversations matches the listing, the create and every
        // /{id}/messages[/stream] call), and the streaming specs fire many of
        // them in one minute: STU-04's abort/recover matrix, STU-17's five
        // settled variants and STU-18's three turns put ~15 requests into a
        // sliding window that the production 30/min bound then refuses -- the
        // captured 429 in the STU-18 trace answers the "New chat" POST. Same
        // sanctioned per-field mechanism as the login knob above; the
        // production values stay pinned by the limiter's own tests, and no
        // spec asserts a real tutor 429.
        RATE_LIMIT_TUTOR_PER_MINUTE: "240",
        RATE_LIMIT_TUTOR_IP_PER_MINUTE: "240",
      },
    },
    {
      // Default harness: the dev server (no build step; strict port so a
      // second Vite instance cannot silently take the next port). E2E_WEB=
      // preview builds once and serves `dist/` instead -- the bundle the
      // container ships, and the only harness where main.tsx registers
      // /sw.js, which offline-shell.spec.ts requires.
      command:
        process.env.E2E_WEB === "preview"
          ? `npm run build && npm run preview -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`
          : `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      cwd: HERE,
      url: WEB_URL,
      reuseExistingServer: !process.env.CI,
      // Covers the production build plus the preview-server start in preview
      // mode (a *failed* build exits early rather than waiting the timeout
      // out); the dev server only needs its cold optimize-deps pass.
      timeout: 600_000,
      ...(DIRECT_API
        ? {
            env: {
              VITE_API_BASE: API_URL,
              // Specs that hit `/api/...` directly (session.spec) go through
              // the vite proxy, whose target must follow the harness API.
              VITE_PROXY_TARGET: API_URL,
            },
          }
        : {}),
    },
  ],
});
