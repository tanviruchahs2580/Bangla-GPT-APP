import { defineConfig, type Plugin } from 'vite'
import { existsSync, statSync } from 'node:fs'
import { extname, join } from 'node:path'
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
 * the CSS was already in the browser; the faces below are the ones that first
 * paint needs (body 400 and heading 700 of the primary family, Bengali and
 * Latin subsets). The URLs are content-hashed, so they are read out of the
 * emitted CSS instead of being hard-coded here.
 *
 * AUD-G-15 follow-up: the Latin subsets used to stay on demand "so they do not
 * compete with the entry bundle", but the prerendered public routes now paint
 * their text at first paint, so a request that only starts at the first layout
 * lands on already-painted text: on /privacy the Latin 400/700 faces arrived
 * 142 ms after the HTML (the preloaded Bengali faces arrived at 20 ms) and the
 * swap moved every section, CLS 0.1367 -- 81 px of document growth measured on
 * the built app. 21 kB of woff2 preloaded with the Bengali faces removes it.
 */
const FIRST_PAINT_FACES = [
  'noto-sans-bengali-bengali-400-normal',
  'noto-sans-bengali-bengali-700-normal',
  'noto-sans-bengali-latin-400-normal',
  'noto-sans-bengali-latin-700-normal',
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

/**
 * AUD-G-15: `npm run build` writes the prerendered public routes to
 * `dist/<route>/index.html`. Production resolves those URL forms without a
 * trailing slash (nginx `try_files $uri $uri/ /index.html`, Vercel's
 * filesystem handler), but Vite 5's preview fallback only looks for
 * `dist/<route>.html` and then `/index.html`, so `/welcome` got the empty SPA
 * shell that the prerender exists to remove -- and it is `vite preview` the
 * Playwright suite drives. Rewrite a directory-index request to the file that
 * is actually there; everything else keeps falling through untouched.
 */
function previewRouteIndex(): Plugin {
  return {
    name: 'bgpt-preview-route-index',
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? '/').split('?')[0]
        const file = join(server.config.root, 'dist', path, 'index.html')
        if (
          path !== '/' &&
          !extname(path) &&
          existsSync(file) &&
          statSync(file).isFile()
        ) {
          req.url = `${path}/index.html`
        }
        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), cacheControl(), previewRouteIndex(), preloadFirstPaintFonts()],
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
