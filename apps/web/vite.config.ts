import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * AUD-G-13: content-hashed build output is immutable; everything else has to
 * be revalidated so a deploy is picked up. `vite preview` mirrors the policy
 * the production server must apply, so the headers are verifiable locally
 * with curl. The deployment configs (deploy/nginx.conf, vercel.json) must
 * match; that change belongs to their owners (see .audit/handoffs).
 */
function cacheControl(): Plugin {
  const IMMUTABLE = 'public, max-age=31536000, immutable'
  const REVALIDATE = 'no-cache'
  return {
    name: 'bgpt-cache-control',
    configurePreviewServer(server) {
      // Runs before sirv, so the header is in place when the file is served.
      // Vite writes only hashed files under /assets/; public/ files keep
      // their names and land at the root.
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? '').split('?')[0]
        res.setHeader(
          'Cache-Control',
          path.startsWith('/assets/') ? IMMUTABLE : REVALIDATE,
        )
        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), cacheControl()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  preview: {
    // S1.14: mirror the dev proxy so the built preview can log in too
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
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
    // e2e/ belongs to the Playwright runner (playwright.config.ts); collecting
    // those specs here fails with "@playwright/test did not expect
    // test.beforeEach() to be called here".
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    // jsdom-heavy RTL files share worker threads; on loaded machines the
    // slowest async queries brush the 5s default. Same assertions, more room.
    testTimeout: 15000,
  },
})
