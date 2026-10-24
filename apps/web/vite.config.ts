import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The E2E harness (apps/web/playwright.config.ts) may run the API on a port
// other than 8000 to dodge other projects' dev servers; specs that call
// `/api/...` directly (session.spec) ride this proxy, so it must follow.
const API_PROXY_TARGET = process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
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
