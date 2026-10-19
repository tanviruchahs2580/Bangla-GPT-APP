/**
 * AUD-G-03 (G-15, E-14): the server stack the Lighthouse CI config audits.
 *
 * `lighthouserc.json` runs this as its `startServerCommand`; `npm run
 * audit:serve` runs it by hand. It exists because the public routes are not
 * purely static: /status and /welcome read the API, and a Lighthouse number
 * measured against a dead API is a different (worse, and unstable) number.
 *
 * What it does, in order:
 *   1. If http://127.0.0.1:8010/health already answers 200, that API is
 *      reused (a developer running the Playwright suite in another terminal
 *      keeps a seeded stack on exactly those ports).
 *   2. Otherwise it seeds a throwaway SQLite database outside the repository
 *      and starts uvicorn with the deterministic `mock` LLM provider.
 *   3. If http://127.0.0.1:5183/ already answers 200, that web server is
 *      reused (that is `vite preview`, which mirrors the production caching
 *      policy); otherwise a static server starts here: `dist/` with SPA
 *      fallback, `/api` proxied the way `vite.config.ts` proxies it, and
 *      `Cache-Control: immutable` on `/assets/*`.
 *   4. Prints `audit stack ready` (the readiness line lighthouserc.json
 *      waits for) and stays alive until killed, so the audit sees a stable
 *      stack for its whole run.
 *
 * Ports are overridable with AUDIT_API_PORT / AUDIT_WEB_PORT; the Lighthouse
 * config's URLs and this script must agree, so change both together.
 * `E2E_PYTHON` selects the interpreter that can import `bangla_gpt_api`
 * (CI exports it after `pip install -e apps/api`); the default is the repo venv.
 *
 * No new dependency: node:http, node:child_process and friends only.
 */

import { spawn } from 'node:child_process'
import { createReadStream, existsSync, statSync } from 'node:fs'
import { createServer, request } from 'node:http'
import { tmpdir } from 'node:os'
import { dirname, extname, join, normalize, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = resolve(HERE, '..')
const REPO_ROOT = resolve(WEB_ROOT, '..', '..')
const DIST = join(WEB_ROOT, 'dist')

const API_PORT = Number(process.env.AUDIT_API_PORT ?? 8010)
const WEB_PORT = Number(process.env.AUDIT_WEB_PORT ?? 5183)
const API_URL = `http://127.0.0.1:${API_PORT}`
const WEB_URL = `http://127.0.0.1:${WEB_PORT}`

const PYTHON =
  process.env.E2E_PYTHON ?? (process.platform === 'win32' ? '.venv/Scripts/python.exe' : 'python')

const children = []
let shuttingDown = false

function log(message) {
  process.stdout.write(`[audit-stack] ${message}\n`)
}

function probe(url) {
  return new Promise((resolveProbe) => {
    const req = request(url, { method: 'GET', timeout: 3000 }, (res) => {
      res.resume()
      resolveProbe(res.statusCode === 200)
    })
    req.on('timeout', () => {
      req.destroy()
      resolveProbe(false)
    })
    req.on('error', () => resolveProbe(false))
    req.end()
  })
}

async function waitFor(url, label, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await probe(url)) return true
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error(`${label} did not answer at ${url} within ${timeoutMs} ms`)
}

function runToCompletion(command, args, env) {
  return new Promise((resolveRun) => {
    const child = spawn(command, args, {
      cwd: REPO_ROOT,
      env,
      stdio: 'inherit',
      shell: false,
    })
    child.on('exit', (code) => resolveRun(code ?? 1))
  })
}

function spawnChild(command, args, env, label) {
  const child = spawn(command, args, {
    cwd: REPO_ROOT,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: false,
  })
  child.stdout.on('data', (chunk) => process.stdout.write(`[audit-stack:${label}] ${chunk}`))
  child.stderr.on('data', (chunk) => process.stdout.write(`[audit-stack:${label}] ${chunk}`))
  child.on('exit', (code) => {
    if (!shuttingDown) log(`${label} exited early with code ${code}`)
  })
  children.push(child)
  return child
}

function apiEnvironment() {
  const dbFile = join(tmpdir(), `bgpt-audit-${Date.now()}-${process.pid}.db`).replace(/\\/g, '/')
  return {
    ...process.env,
    DATABASE_URL: `sqlite:///${dbFile}`,
    ENV: 'ci',
    LLM_PROVIDER: 'mock',
    JOBS_BACKEND: 'inline',
    SMTP_HOST: '',
    SENTRY_DSN: '',
    ALLOWED_ORIGINS: `http://127.0.0.1:${WEB_PORT},http://localhost:${WEB_PORT}`,
  }
}

/* --- static server: dist/ with SPA fallback and the preview caching policy --- */

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
  '.webm': 'video/webm',
}

function serveStatic(req, res) {
  const rawPath = (req.url ?? '/').split('?')[0]
  const path = rawPath === '/' ? '/index.html' : rawPath
  // normalize() collapses `..` so a traversal attempt cannot escape dist/.
  const candidate = normalize(join(DIST, decodeURIComponent(path)))
  if (!candidate.startsWith(DIST)) {
    res.writeHead(403).end('forbidden')
    return
  }
  const file =
    existsSync(candidate) && statSync(candidate).isFile() ? candidate : join(DIST, 'index.html')
  res.setHeader(
    'Cache-Control',
    rawPath.startsWith('/assets/') ? 'public, max-age=31536000, immutable' : 'no-cache',
  )
  res.setHeader('Content-Type', MIME[extname(file)] ?? 'application/octet-stream')
  createReadStream(file).pipe(res)
}

function proxyApi(req, res) {
  const target = req.url.replace(/^\/api/, '') || '/'
  const proxied = request(
    `${API_URL}${target}`,
    {
      method: req.method,
      headers: { ...req.headers, host: `127.0.0.1:${API_PORT}` },
    },
    (upstream) => {
      res.writeHead(upstream.statusCode ?? 502, upstream.headers)
      upstream.pipe(res)
    },
  )
  proxied.on('error', () => res.writeHead(502).end('api unreachable'))
  req.pipe(proxied)
}

function startStaticServer() {
  const server = createServer((req, res) => {
    if ((req.url ?? '').startsWith('/api')) proxyApi(req, res)
    else serveStatic(req, res)
  })
  server.listen(WEB_PORT, '127.0.0.1')
  log(`static server listening on ${WEB_URL} (serving ${DIST})`)
}

/* --- startup --- */

if (!existsSync(join(DIST, 'index.html'))) {
  log(`dist/index.html is missing -- run \`npm run build\` first (looked in ${DIST})`)
  process.exit(1)
}

if (await probe(`${API_URL}/health`)) {
  log(`reusing API already listening on ${API_URL}`)
} else {
  const env = apiEnvironment()
  log('seeding audit accounts')
  const seedCode = await runToCompletion(
    PYTHON,
    [join('apps', 'web', 'e2e', 'seed_e2e_users.py')],
    env,
  )
  if (seedCode !== 0) {
    log(`seed failed with exit code ${seedCode}`)
    process.exit(1)
  }
  spawnChild(
    PYTHON,
    [
      '-m',
      'uvicorn',
      'bangla_gpt_api.main:app',
      '--app-dir',
      'apps/api/src',
      '--host',
      '127.0.0.1',
      '--port',
      String(API_PORT),
    ],
    env,
    'api',
  )
}

if (await probe(WEB_URL)) {
  log(`reusing web server already listening on ${WEB_URL}`)
} else {
  startStaticServer()
}

try {
  await waitFor(`${API_URL}/health`, 'API', 120_000)
  await waitFor(WEB_URL, 'web server', 120_000)
} catch (error) {
  log(String(error))
  for (const child of children) child.kill()
  process.exit(1)
}

log(`audit stack ready (api=${API_URL}, web=${WEB_URL})`)

function shutdown() {
  shuttingDown = true
  for (const child of children) child.kill()
  process.exit(0)
}
process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)
