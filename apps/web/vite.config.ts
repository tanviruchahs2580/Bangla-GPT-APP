import { gzipSync } from "node:zlib";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// The E2E harness (apps/web/playwright.config.ts) may run the API on a port
// other than 8000 to dodge other projects' dev servers; specs that call
// `/api/...` directly (session.spec) ride this proxy, so it must follow.
const API_PROXY_TARGET = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";

/**
 * FE-12: per-chunk gzip budgets. The two entries that dominate the initial
 * payload are pinned close to their measured sizes (index 103.9 kB,
 * safeMarkdown 119.6 kB gzip on 2026-10-29) so growth is a failed build, not
 * a discovery; every route chunk gets the general cap. Budgets are gzip bytes
 * because that is what the student's connection pays.
 */
const CHUNK_BUDGETS: Array<{ match: RegExp; bytes: number; label: string }> = [
  { match: /^assets\/index-.*\.js$/, bytes: 125_000, label: "app entry" },
  {
    match: /^assets\/safeMarkdown-.*\.js$/,
    bytes: 135_000,
    label: "markdown + KaTeX",
  },
];
const DEFAULT_CHUNK_BUDGET = 110_000;

function bundleBudget(): Plugin {
  return {
    name: "bundle-budget",
    apply: "build",
    generateBundle(_options, bundle) {
      const violations: string[] = [];
      const report: string[] = [];
      for (const [fileName, output] of Object.entries(bundle)) {
        if (output.type !== "chunk") continue;
        const gzipBytes = gzipSync(output.code).length;
        const budget =
          CHUNK_BUDGETS.find((b) => b.match.test(fileName))?.bytes ??
          DEFAULT_CHUNK_BUDGET;
        const label =
          CHUNK_BUDGETS.find((b) => b.match.test(fileName))?.label ?? "route";
        report.push(
          `${fileName}: ${gzipBytes} B gzip / ${budget} B (${label})`,
        );
        if (gzipBytes > budget) {
          violations.push(`${fileName} (${label}): ${gzipBytes} > ${budget}`);
        }
      }
      this.info(`bundle budget:\n  ${report.join("\n  ")}`);
      if (violations.length > 0) {
        this.error(
          `bundle budget exceeded:\n  ${violations.join("\n  ")}\n` +
            "Raise the budget in vite.config.ts only with a measured reason.",
        );
      }
    },
  };
}

/**
 * FE-12: the first Bangla paint waits on a font the CSS discovers after the
 * stylesheet loads. The two body weights are preloaded from the emitted
 * filenames so the browser fetches them in parallel with the CSS.
 */
function preloadBengaliFonts(): Plugin {
  const WANTED = [
    /noto-sans-bengali-bengali-400-normal.*\.woff2$/,
    /noto-sans-bengali-bengali-700-normal.*\.woff2$/,
  ];
  return {
    name: "preload-bengali-fonts",
    apply: "build",
    enforce: "post",
    transformIndexHtml(html, ctx) {
      const fonts = Object.keys(ctx.bundle ?? {}).filter((name) =>
        WANTED.some((w) => w.test(name)),
      );
      return {
        html,
        tags: fonts.map((fileName) => ({
          tag: "link",
          attrs: {
            rel: "preload",
            as: "font",
            type: "font/woff2",
            href: `/${fileName}`,
            crossorigin: "",
          },
          injectTo: "head" as const,
        })),
      };
    },
  };
}

export default defineConfig({
  plugins: [react(), bundleBudget(), preloadBengaliFonts()],
  build: {
    // Sourcemap policy: production builds ship NO sourcemaps. The servers
    // (deploy/nginx.conf, vercel.json) are public; a map would publish the
    // full source of the app including the auth layer to anyone with devtools.
    // Debug on the `staging` lane with `vite build --sourcemap` instead.
    sourcemap: false,
    // FE-18: the support matrix from .browserslistrc — entry-level Android
    // WebViews (Chrome 100 era) and the iOS WebKit that ships with them.
    target: ["chrome100", "firefox100", "safari15", "edge100"],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: API_PROXY_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  preview: {
    // S1.14: mirror the dev proxy so the built preview can log in too
    proxy: {
      '/api': {
        target: API_PROXY_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: false,
    // The Playwright suite (e2e/*.spec.ts) is a different runner: without
    // this exclusion vitest collects those files, fails them all at import
    // (playwright's test() outside its own runner), and 14 phantom file
    // failures shadow the real unit results.
    exclude: ['**/node_modules/**', 'e2e/**', 'dist/**'],
    // jsdom-heavy RTL files share worker threads; on loaded machines the
    // slowest async queries brush the 5s default. Same assertions, more room.
    testTimeout: 15000,
    coverage: {
      // H-03: the backend enforces fail_under=80 with branch coverage; the
      // frontend suite ran with no measurement at all, so regression was
      // invisible. Baselines are the measured values on the current suite —
      // raised deliberately as the floor moves, never skipped (thresholds
      // AUTO-fail `npm run test:coverage` when a change removes tests or
      // adds untested code paths).
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/test/**', 'src/types.ts'],
      all: true,
      reporter: ['text', 'html'],
      reportsDirectory: 'coverage/vitest',
      thresholds: {
        // Measured baselines of the current suite (2026-10-24: lines 70.2,
        // branches 62.9, functions 62.8, statements 72.5) minus a small
        // margin, so the gate blocks regressions without failing today.
        // Raise these as coverage grows; never lower or skip them.
        lines: 68,
        functions: 60,
        branches: 60,
        statements: 70,
      },
    },
  },
})
