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

/**
 * AUD-G-03 (G-15): the webfonts that paint the first screen must not wait for
 * the stylesheet to arrive and be parsed. Lighthouse measured the LCP element
 * on /welcome and /login as text whose font request only started ~500 ms after
 * the CSS was already in the browser; the two faces below are the ones that
 * first paint needs (body 400 and heading 700 of the primary family, Bengali
 * subset -- the Latin subsets stay on demand so they do not compete with the
 * entry bundle). The URLs are content-hashed, so they are read out of the
 * emitted CSS instead of being hard-coded here.
 */
const FIRST_PAINT_FACES = [
  'noto-sans-bengali-bengali-400-normal',
  'noto-sans-bengali-bengali-700-normal',
]

function preloadFirstPaintFonts(): Plugin {
  return {
    name: 'bgpt-preload-first-paint-fonts',
    apply: 'build',
    enforce: 'post',
    transformIndexHtml(html, ctx) {
      const bundle = ctx.bundle
      if (!bundle) return html
      const found = new Map<string, string>()
      for (const [fileName, output] of Object.entries(bundle)) {
        if (output.type !== 'asset' || !fileName.endsWith('.css')) continue
        const css = output.source.toString()
        for (const face of FIRST_PAINT_FACES) {
          const match = css.match(new RegExp(`assets/(${face}-[A-Za-z0-9_-]+\\.woff2)`))
          if (match && !found.has(face)) found.set(face, match[1])
        }
      }
      return {
        html,
        tags: [...found.values()].map((file) => ({
          tag: 'link',
          attrs: {
            rel: 'preload',
            as: 'font',
            type: 'font/woff2',
            href: `/assets/${file}`,
            crossorigin: '',
          },
          injectTo: 'head' as const,
        })),
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), cacheControl(), preloadFirstPaintFonts()],
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
