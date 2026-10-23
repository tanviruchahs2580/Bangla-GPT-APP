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
        lines: 55,
        functions: 55,
        branches: 75,
        statements: 55,
      },
    },
  },
})
