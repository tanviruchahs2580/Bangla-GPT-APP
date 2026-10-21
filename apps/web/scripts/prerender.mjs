/**
 * AUD-G-15 (G-15, G-19): static prerender for the seven public routes.
 *
 * The audit's measured problem: /welcome, /login, /register, /forgot,
 * /privacy, /terms and /status are client-rendered, so their first paint is a
 * blank body whose LCP element (the H1 on /welcome, a `<p class="muted">` on
 * /privacy) only exists after the entry bundle has been downloaded, compiled
 * and run -- 3.4-3.7 s of FCP on the audit host, with a 4-20 ms TTFB, i.e. the
 * whole LCP budget spent client-side. Prerendering moves that text into the
 * served HTML: the same page, painted at first paint, then hydrated.
 *
 * What it does, per route: drive the *built* `dist/` in Chromium over a
 * throwaway static server, wait for the real page to commit (each route's
 * marker below, which the pending shell does not contain), and write
 * `dist/<route>/index.html` holding the built template's `<head>` and body
 * scripts verbatim plus the rendered `#root` markup.
 *
 * Deliberate choices:
 *   - No `waitUntil: "networkidle"`, and every `/api/**` request is left
 *     hanging (`page.route` with no handler): /status fetches in an effect and
 *     must be snapshotted in its deterministic pre-data render -- neither a
 *     live payload nor an error state is a prerender.
 *   - The output is static and deterministic: no timestamps, no per-run ids.
 *     The one date in the markup is the footer's copyright year, which is
 *     fixed for a build.
 *   - Hydration (`src/main.tsx`) requires the prerendered state of an
 *     anonymous visitor to equal the client's first render; the default
 *     language is bn and there is no token in a fresh browser context, which
 *     is exactly the state this script renders in.
 *   - `dist/index.html` is left untouched: it stays the SPA fallback for every
 *     other route.
 *
 * The browser comes from the installed `@playwright/test`; a machine that has
 * not run `npx playwright install chromium` (CI's web job, the Alpine Docker
 * build) gets a loud skip instead of a failed build -- the app then ships
 * exactly what it shipped before this script existed, with no prerender.
 */

import { chromium } from '@playwright/test'
import {
  createReadStream,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
  writeFileSync,
} from 'node:fs'
import { createServer } from 'node:http'
import { dirname, extname, join, normalize, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const DIST = resolve(HERE, '..', 'dist')

const TEMPLATE_SLOT = '<div id="root"></div>'

/**
 * The routes to prerender, with the selector that only the real page has: the
 * pending shell (`Loading`) renders a `<main class="container">` with
 * skeletons, so a route is ready to snapshot when its own marker is attached.
 */
const ROUTES = [
  { path: '/welcome', marker: 'h1.landing-title' },
  { path: '/login', marker: 'form #email', preloadHero: true },
  { path: '/register', marker: 'form #name', preloadHero: true },
  { path: '/forgot', marker: 'form #femail' },
  { path: '/privacy', marker: 'main.card-legal h2' },
  { path: '/terms', marker: 'main.card-legal h2' },
  { path: '/status', marker: 'main.card-narrow h2' },
]

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
}

/**
 * Serialize `#root` the way React's own server renderer does, which is not what
 * `innerHTML` produces: JSX with two adjacent expressions (`{a} · {b}`) is two
 * text nodes on the client, and an HTML parser merges them into one on the way
 * back in -- hydration then fails ("Text content did not match", React #418,
 * which `e2e/crawl.spec.ts` catches as a console error). React's SSR inserts a
 * `<!-- -->` separator between adjacent text nodes for exactly this reason, and
 * so do we: the footer, the legal section headings and the register form's
 * consent label all use the pattern.
 *
 * Raw-text elements (`<script>`, `<style>`) do not occur inside `#root` on the
 * prerendered routes; `<textarea>` content is escaped, which is what it needs.
 * The function is injected into the page (it has to run against the live DOM).
 */
function installSerializer() {
  const VOID_ELEMENTS = new Set([
    'area',
    'base',
    'br',
    'col',
    'embed',
    'hr',
    'img',
    'input',
    'link',
    'meta',
    'param',
    'source',
    'track',
    'wbr',
  ])
  function escapeText(value) {
    return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  }
  function serialize(node) {
    if (node.nodeType === Node.TEXT_NODE) return escapeText(node.data)
    if (node.nodeType === Node.COMMENT_NODE) return `<!--${node.data}-->`
    if (node.nodeType !== Node.ELEMENT_NODE) return ''
    // localName, not toLowerCase(): SVG keeps its camelCase element names.
    const name = node.localName
    let out = `<${name}`
    for (const attribute of node.attributes) {
      out += ` ${attribute.name}="${attribute.value.replaceAll('&', '&amp;').replaceAll('"', '&quot;')}"`
    }
    out += '>'
    if (VOID_ELEMENTS.has(name)) return out
    return `${out}${serializeChildren(node)}</${name}>`
  }
  function serializeChildren(parent) {
    let out = ''
    let previousWasText = false
    for (const child of parent.childNodes) {
      const isText = child.nodeType === Node.TEXT_NODE
      if (isText && previousWasText) out += '<!-- -->'
      out += serialize(child)
      previousWasText = isText
    }
    return out
  }
  window.__prerenderSerialize = (root) => serializeChildren(root)
}

/** `dist/` with the SPA fallback: the prerender only ever needs the template. */
function serveDist(server) {
  server.on('request', (req, res) => {
    const rawPath = (req.url ?? '/').split('?')[0]
    const path = rawPath === '/' ? '/index.html' : rawPath
    const candidate = normalize(join(DIST, decodeURIComponent(path)))
    const file =
      candidate.startsWith(DIST) &&
      existsSync(candidate) &&
      statSync(candidate).isFile()
        ? candidate
        : join(DIST, 'index.html')
    res.setHeader('Content-Type', MIME[extname(file)] ?? 'application/octet-stream')
    createReadStream(file).pipe(res)
  })
}

function listen(server) {
  return new Promise((resolveListen, rejectListen) => {
    server.once('error', rejectListen)
    server.listen(0, '127.0.0.1', () => resolveListen(server.address().port))
  })
}

async function launchBrowser() {
  try {
    return await chromium.launch()
  } catch (error) {
    const reason = error instanceof Error ? error.message.split('\n')[0] : String(error)
    console.warn(
      `[prerender] SKIPPED: ${reason}\n` +
        '[prerender] dist/index.html still serves every route as the SPA fallback, ' +
        'but the public routes are NOT prerendered. Run `npx playwright install chromium` ' +
        'before `npm run build` to ship them.',
    )
    return null
  }
}

async function renderRoot(page, baseUrl, route) {
  await page.goto(`${baseUrl}${route.path}`, {
    waitUntil: 'domcontentloaded',
    timeout: 30_000,
  })
  await page.waitForSelector(route.marker, { state: 'visible', timeout: 30_000 })
  return page.evaluate((where) => {
    const root = document.getElementById('root')
    if (!root) throw new Error('#root is missing from the served document')
    // An error state is not a prerender: a page that failed to boot must fail
    // the build rather than ship a snapshot of its own error message.
    if (root.querySelector('[role="alert"], .error')) {
      throw new Error(`the page rendered an error state: ${where}`)
    }
    return window.__prerenderSerialize(root)
  }, route.path)
}

const template = readFileSync(join(DIST, 'index.html'), 'utf8')
const slot = template.indexOf(TEMPLATE_SLOT)
if (slot === -1) {
  throw new Error(
    `dist/index.html has no \`${TEMPLATE_SLOT}\`, so the prerender has nowhere to put the ` +
      'rendered markup -- check index.html in the repository, then rebuild.',
  )
}

/**
 * AUD-G-15: a prerendered page must not wait for a render-blocking request.
 *
 * With the text in the HTML, the first paint is bounded by the parser-blocking
 * resources, and Lighthouse measured exactly those on the built app: the
 * stylesheet (82.8 kB, "wastedMs 1072") and `/theme-boot.js` (1.1 kB, 322 ms),
 * with 89% of the LCP spent in "render delay" rather than in transfer. Both are
 * small enough to inline on the seven public pages -- the CSS is the same
 * document-wide sheet the SPA needs, so inlining it removes the request without
 * removing anything the app uses, and the theme script keeps doing its job of
 * setting `data-theme` before the first paint, it just does it without a round
 * trip. The stylesheet link is dropped from the prerendered pages only; the
 * file stays in `dist/` for the SPA shell and for every future build.
 */
function inlineFirstPaintResources(html) {
  const withInlineTheme = html.replace(
    /<script src="(\/theme-boot\.js)"><\/script>/,
    (tag, href) => {
      const file = join(DIST, href)
      if (!existsSync(file)) return tag
      return `<script>${readFileSync(file, 'utf8').trim()}</script>`
    },
  )
  const withInlineCss = withInlineTheme.replace(
    /<link rel="stylesheet" crossorigin href="(\/assets\/[^"]+\.css)"\s*\/?>/,
    (tag, href) => {
      const file = join(DIST, href)
      if (!existsSync(file)) return tag
      // `</style` cannot appear in the sheet; assert rather than escape, so a
      // future stylesheet that contains it fails the build instead of shipping
      // a broken document.
      const css = readFileSync(file, 'utf8')
      if (css.includes('</style')) {
        throw new Error(`${href} contains "</style"; inlining it would break the document`)
      }
      return `<style data-inlined-stylesheet="${href}">${css}</style>`
    },
  )
  if (withInlineCss === html) {
    console.warn(
      '[prerender] WARNING: no stylesheet or theme script matched to inline; ' +
        'the prerendered pages will wait for render-blocking requests (LCP).',
    )
  }
  return withInlineCss
}

/**
 * AUD-G-15: the login and register pages paint their hero from a CSS custom
 * property (`--splash-bg-image`), and Chrome only discovers a background image
 * after the stylesheet is parsed and the rule matched -- on the simulated mobile
 * profile that discovery plus an 84 kB JPEG pushed those two routes' LCP past
 * the budget while every text route sat at 2.1 s. Both artworks are
 * content-hashed, so the URLs are read out of the emitted stylesheet here, and
 * only the two routes that use them preload them (a preload on /privacy would be
 * 84 kB of nothing).
 */
function splashImagePreloads() {
  const css = readdirSync(join(DIST, 'assets'))
    .filter((name) => name.endsWith('.css'))
    .map((name) => readFileSync(join(DIST, 'assets', name), 'utf8'))
    .join(' ')
  const find = (stem) => {
    // Character classes instead of the usual shorthand: this pattern is built
    // from a string, where a backslash is an escape and silently drops the
    // metacharacter (measured: the warning below fired and the two hero routes
    // shipped without their preloads).
    const match = css.match(new RegExp('/assets/' + stem + '-[A-Za-z0-9_-]+[.]jpg'))
    return match ? match[0] : null
  }
  const mobile = find('login-bg-mobile')
  const desktop = find('login-bg-desktop')
  const tags = []
  if (mobile) {
    tags.push(`<link rel="preload" as="image" href="${mobile}" media="(max-width: 899px)">`)
  }
  if (desktop) {
    tags.push(`<link rel="preload" as="image" href="${desktop}" media="(min-width: 900px)">`)
  }
  if (!tags.length) {
    console.warn('[prerender] WARNING: no splash artwork found in the built CSS to preload')
  }
  return tags.join('')
}

const splashPreloads = splashImagePreloads()
const inlinedTemplate = inlineFirstPaintResources(template)
const slotInlined = inlinedTemplate.indexOf(TEMPLATE_SLOT)
// Head (font preloads, the inlined theme script and stylesheet) and the body's
// entry loader are kept verbatim from the built template; the root's closing
// tag is re-emitted because the slot consumed it.
const head = inlinedTemplate.slice(0, slotInlined + '<div id="root">'.length)
const headForm = head.replace(
  '</head>',
  `${splashPreloads}</head>`,
)
const tail = `</div>${inlinedTemplate.slice(slotInlined + TEMPLATE_SLOT.length)}`

const browser = await launchBrowser()
if (browser) {
  const server = createServer()
  serveDist(server)
  const port = await listen(server)
  const baseUrl = `http://127.0.0.1:${port}`
  try {
    const context = await browser.newContext({
      // The offline shell is production-only; blocking it keeps a cached
      // document from ever being what gets snapshotted.
      serviceWorkers: 'block',
      viewport: { width: 1280, height: 720 },
    })
    // /api is left unanswered on purpose: /status must be captured before its
    // fetch can resolve into either a payload or an error message. The block is
    // installed at the fetch layer, not only as a route: the build under test
    // may carry an absolute API base (`e2e/perf.spec.ts` builds with
    // VITE_API_BASE pointed at its own port), and a request that raced past the
    // route pattern would fail fast against a port with nothing listening --
    // the page then rendered its error state and the guard below refused the
    // snapshot (measured: intermittent, CPU-load dependent).
    await context.addInitScript(() => {
      const original = window.fetch
      window.fetch = function (input, init) {
        const url =
          typeof input === 'string' ? input : (input && input.url) || ''
        if (url.includes('/api/')) {
          // The app bounds every request (`REQUEST_TIMEOUT_MS`, 20 s); on a
          // loaded build host that deadline can expire while /status is still
          // waiting for its (never-answered) API call, the page then renders
          // its error state and the snapshot guard refuses the snapshot --
          // measured intermittently, and only on the one fetch-driven public
          // route. Dropping the abort signal for the blocked call makes the
          // captured state a property of the page, not of the machine's load.
          if (init && init.signal) init = { ...init, signal: undefined }
          return new Promise(() => {})
        }
        return original.call(this, input, init)
      }
    })
    const page = await context.newPage()
    await page.route('**/api/**', () => {})
    await page.addInitScript(installSerializer)
    for (const route of ROUTES) {
      const markup = await renderRoot(page, baseUrl, route)
      const outDir = join(DIST, route.path.slice(1))
      mkdirSync(outDir, { recursive: true })
      const headForRoute = route.preloadHero ? headForm : head
      const document = headForRoute + markup + tail
      writeFileSync(join(outDir, 'index.html'), document)
      console.log(`[prerender] ${route.path} -> dist${route.path}/index.html`)
    }
    await context.close()
  } finally {
    await browser.close()
    server.close()
  }
}
