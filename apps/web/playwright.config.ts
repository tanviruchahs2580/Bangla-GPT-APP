import { defineConfig, devices } from "@playwright/test";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * AUD-EF-02 / E-10 (issue #38): browser end-to-end smoke suite.
 *
 * Scope: one Chromium project driving the *real* web app against the *real*
 * API with the deterministic `mock` LLM provider. The five-role critical
 * journeys are exercised by `e2e/smoke.spec.ts`; nothing here is mocked at the
 * HTTP layer, so a broken route, a broken auth guard or a broken proxy fails
 * the suite. WebKit and Firefox are deliberately NOT here: they run on the
 * nightly schedule (.github/workflows/nightly.yml), because their install cost
 * does not belong on every pull request.
 *
 * Run it:
 *   apps/web> npx playwright test
 * The suite starts both servers itself: a seeded API (uvicorn, port 8000) and
 * the built app (`npm run build` + `vite preview`, port 5173, whose /api proxy
 * targets 127.0.0.1:8000). Set E2E_PYTHON when the API's dependencies live
 * outside the repo venv (CI does exactly that).
 *
 * Determinism: no fixed sleeps anywhere -- assertions rely on Playwright's
 * auto-waiting; `trace`/`screenshot` fire on failure only; one worker, because
 * the journeys share seeded rows (the parent-link test consumes an invite
 * code).
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
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5173);
const API_URL = `http://127.0.0.1:${API_PORT}`;
const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;

// Default wiring, identical to CI: the app calls `/api/*` and the Vite dev
// server proxies it to 127.0.0.1:8000 (vite.config.ts). E2E_API_PORT /
// E2E_WEB_PORT exist for shared machines where those ports are taken; when the
// API port is overridden the proxy target cannot follow, so the dev server is
// pointed straight at the API with VITE_API_BASE and the API's
// ALLOWED_ORIGINS admits the dev-server origin.
const DIRECT_API = API_PORT !== 8000;
const WEB_ORIGINS = `http://127.0.0.1:${WEB_PORT},http://localhost:${WEB_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  // traces/screenshots/videos land under an already-ignored path (coverage/).
  outputDir: "./coverage/e2e/results",
  // Generous because the whole app is a lazy-loaded module graph: the first
  // navigation of a run pays for the compile/loading of every route chunk.
  // The per-assertion default stays tight so a broken selector still fails fast.
  timeout: 120_000,
  expect: {
    timeout: 20_000,
    // AUD-G-07: one reviewed baseline set serves every runner -- the platform
    // suffix is dropped from the snapshot file name (snapshotPathTemplate
    // below) and a 2% pixel-ratio difference is tolerated so cross-platform
    // text rasterisation does not fail the review it is meant to support.
    // The matrix and the review note live in e2e/visual.spec.ts.
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.02,
      animations: "disabled",
      caret: "hide",
    },
  },
  snapshotPathTemplate: "{testDir}/__screenshots__/{testFileName}/{arg}{ext}",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  // One retry on CI: a second failure is real, the first may be runner noise.
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["list"],
    ["junit", { outputFile: "coverage/e2e/junit.xml" }],
    ["html", { outputFolder: "coverage/e2e/html", open: "never" }],
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
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Seed first (roles cannot be self-registered), then serve. One shell so
      // both processes inherit the same DATABASE_URL. The long-history seed
      // (AUD-G-19) is what perf.spec.ts throttles; it is idempotent and costs
      // 120 inserts on a fresh database.
      command: `"${PYTHON}" apps/web/e2e/seed_e2e_users.py && "${PYTHON}" apps/web/e2e/seed_long_history.py && "${PYTHON}" -m uvicorn bangla_gpt_api.main:app --app-dir apps/api/src --host 127.0.0.1 --port ${API_PORT}`,
      cwd: REPO_ROOT,
      url: `${API_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        DATABASE_URL,
        // mock provider: no API key, no network, deterministic answers.
        ENV: "ci",
        LLM_PROVIDER: "mock",
        // jobs run inline in-process; no Redis/ARQ is needed for the smoke.
        JOBS_BACKEND: "inline",
        ALLOWED_ORIGINS: WEB_ORIGINS,
        SMTP_HOST: "",
        SENTRY_DSN: "",
        // The suite signs in dozens of times from one IP (every spec starts
        // with `signIn`), which is what the per-IP login limiter exists to
        // stop in production. Under the default 10/min the later specs -- a
        // two-login test such as the parent-invite smoke -- got a 429, the UI
        // stayed on /login and the spec failed on
        // `expect(page).not.toHaveURL(/login/)`: a harness limit, not a
        // product defect. Raised for the harness only; the limiter's own tests
        // pin the production value.
        RATE_LIMIT_LOGIN_PER_MINUTE: "240",
      },
    },
    {
      // The *built* app, not the dev server: `vite preview` serves the same
      // bundle the container ships (its proxy mirrors the dev proxy in
      // vite.config.ts), which keeps the run fast and the results faithful.
      // --host 127.0.0.1: Vite's default `localhost` resolves to ::1 on some
      // hosts, which the probe URL (and the browser's target) does not.
      command: `npm run build && npm run preview -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      cwd: HERE,
      url: WEB_URL,
      reuseExistingServer: !process.env.CI,
      // Covers the production build plus the preview server start. Generous on
      // purpose: a shared CI runner builds in about a minute, a loaded
      // developer machine was measured at ~3.5 min, and a *failed* build exits
      // early (reported immediately) rather than waiting this timeout out.
      timeout: 600_000,
      ...(DIRECT_API ? { env: { VITE_API_BASE: API_URL } } : {}),
    },
  ],
});
