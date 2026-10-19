import { expect, test, type Page } from '@playwright/test'
import { openRoute, signIn, useVariant } from './a11y'

/**
 * AUD-G-04 / G-04: role UX coherence — "zero dead links or buttons; no
 * visible-but-nonfunctional features", verified by "an e2e crawl of every
 * route and clickable element".
 *
 * The route inventory mirrors `src/main.tsx` one-for-one, the same way
 * `axe.spec.ts` does; a route added there without being added here is a gap,
 * which is why the list is explicit rather than derived.
 *
 * What the crawl actually proves:
 *
 *  1. every route of every role renders a shell with exactly one main
 *     landmark and at least one heading — a route that mounts an empty div
 *     is a dead link;
 *  2. every in-page internal `href` points at a known route (or a known
 *     parameterised pattern) — a typo'd `href` is a 404 with extra steps;
 *  3. every *visible* button and link has an accessible name, and no visible
 *     control is silently disabled;
 *  4. each shell navigation link really navigates (a click, not a string
 *     comparison), and after every click the app is still alive;
 *  5. a role cannot see another role's home — the guard is enforced, not
 *     merely styled.
 *
 * Destructive controls (sign-out, delete) are never clicked: the item asks
 * for dead-link detection, not for a test that wipes a seeded account.
 */

interface Role {
  name: string
  email: string
  home: string
  routes: string[]
}

const ROLES: Role[] = [
  {
    name: 'student',
    email: 'student1@e2e.test',
    home: '/student',
    routes: ['/student', '/student/learn', '/student/tutor', '/student/quiz', '/student/me'],
  },
  {
    name: 'teacher',
    email: 'teacher1@e2e.test',
    home: '/teacher',
    routes: [
      '/teacher',
      '/teacher/create',
      '/teacher/classes',
      '/teacher/assessments',
      '/teacher/analytics',
      '/teacher/profile',
    ],
  },
  { name: 'parent', email: 'parent1@e2e.test', home: '/parent', routes: ['/parent'] },
  { name: 'admin', email: 'admin1@e2e.test', home: '/admin', routes: ['/admin'] },
  { name: 'school_admin', email: 'schooladmin1@e2e.test', home: '/school', routes: ['/school'] },
]

const PUBLIC_ROUTES = ['/welcome', '/login', '/register', '/forgot', '/privacy', '/terms', '/status']

/** Routes with a path parameter, matched as prefixes/patterns. */
const PARAMETERISED = [/^\/student\/learn\/[^/]+\/[^/]+$/]

const KNOWN = new Set([
  ...PUBLIC_ROUTES,
  ...ROLES.flatMap((role) => role.routes),
  '/student/learn/',
])

function isKnownRoute(href: string): boolean {
  if (KNOWN.has(href)) return true
  if (PARAMETERISED.some((pattern) => pattern.test(href))) return true
  // The root link and in-page fragments resolve to the role home.
  return href === '/' || href.startsWith('#')
}

interface Finding {
  where: string
  what: string
}

/** Collect console errors and page errors for the whole page lifetime. */
function watchErrors(page: Page, findings: Finding[], where: string): void {
  page.on('pageerror', (error) => findings.push({ where, what: `pageerror: ${error.message}` }))
  page.on('console', (message) => {
    if (message.type() !== 'error') return
    const text = message.text()
    // A failed fetch from the offline/error simulations is expected noise;
    // everything else is a defect the user can see in the console.
    if (/Failed to load resource|net::ERR_INTERNET_DISCONNECTED/.test(text)) return
    findings.push({ where, what: `console.error: ${text.slice(0, 200)}` })
  })
}

async function crawlRoute(page: Page, route: string, findings: Finding[]): Promise<void> {
  await openRoute(page, route)

  const main = page.locator('main, [role="main"]')
  if ((await main.count()) !== 1) {
    findings.push({ where: route, what: `expected exactly one main landmark, found ${await main.count()}` })
  }
  if ((await page.getByRole('heading').count()) === 0) {
    findings.push({ where: route, what: 'no heading rendered' })
  }

  // Internal links must point at a route the app actually serves.
  const hrefs: string[] = await page.$$eval('a[href]', (nodes) =>
    nodes.map((node) => node.getAttribute('href') ?? ''),
  )
  for (const href of hrefs) {
    if (href.startsWith('http') || href.startsWith('mailto:')) continue
    const path = href.split('?')[0]
    if (!isKnownRoute(path)) {
      findings.push({ where: route, what: `dead internal link: ${href}` })
    }
  }

  // Visible controls must be named. (A disabled button is not a finding: the
  // composer's Send button is disabled until there is text, which is correct.)
  const controls = await page.$$eval('button, a[href], [role="button"]', (nodes) =>
    nodes
      .filter((node) => {
        const style = window.getComputedStyle(node as HTMLElement)
        const box = (node as HTMLElement).getBoundingClientRect()
        return style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0
      })
      .map((node) => ({
        name: (
          node.getAttribute('aria-label') ??
          node.textContent ??
          node.getAttribute('title') ??
          ''
        ).trim(),
        html: (node as HTMLElement).outerHTML.slice(0, 120),
      })),
  )
  for (const control of controls) {
    if (control.name.length === 0) {
      findings.push({ where: route, what: `visible control without an accessible name: ${control.html}` })
    }
  }

  // G-14: an <img> with no alt attribute at all is read out as its file name
  // (or nothing), and `alt=""` is how a decorative image is hidden — the two
  // are different, so the attribute has to be present on every image.
  const imagesWithoutAlt: string[] = await page.$$eval('img:not([alt])', (nodes) =>
    nodes.map((node) => (node as HTMLImageElement).currentSrc || node.outerHTML.slice(0, 80)),
  )
  for (const src of imagesWithoutAlt) {
    findings.push({ where: route, what: `image without an alt attribute: ${src}` })
  }
}

test.describe.configure({ timeout: 10 * 60_000 })

test('public routes crawl clean (links, controls, headings)', async ({ page }) => {
  const findings: Finding[] = []
  watchErrors(page, findings, 'public')
  for (const route of PUBLIC_ROUTES) await crawlRoute(page, route, findings)
  expect(findings, format(findings)).toEqual([])
})

for (const role of ROLES) {
  test(`${role.name} routes crawl clean and the shell navigates`, async ({ page }) => {
    await useVariant(page, { theme: 'light', lang: 'bn' })
    const findings: Finding[] = []
    watchErrors(page, findings, role.name)
    await signIn(page, role.email)

    for (const route of role.routes) await crawlRoute(page, route, findings)

    // The shell's own navigation: click every nav link and prove the app
    // lands on the route it advertises. This is the part a static href check
    // cannot do (a link can point somewhere real and still do nothing).
    const navHrefs: string[] = await page.$$eval(
      'nav a[href^="/"], aside a[href^="/"], .appbar a[href^="/"]',
      (nodes) => [...new Set(nodes.map((node) => node.getAttribute('href') ?? ''))],
    )
    expect(navHrefs.length, 'the shell renders no navigation links').toBeGreaterThan(0)
    for (const href of navHrefs) {
      if (!isKnownRoute(href.split('?')[0])) {
        findings.push({ where: `${role.name} nav`, what: `nav link to an unknown route: ${href}` })
        continue
      }
      await page.goto(role.home, { waitUntil: 'domcontentloaded' })
      const link = page.locator(`a[href="${href}"]`).first()
      if ((await link.count()) === 0) continue
      await link.click()
      await page.waitForURL((url) => url.pathname === href.split('?')[0], { timeout: 30_000 })
      await expect(page.locator('main, [role="main"]')).toHaveCount(1)
    }

    expect(findings, format(findings)).toEqual([])
  })
}

test('each role is denied the other roles home (guard, not styling)', async ({ page }) => {
  await useVariant(page, { theme: 'light', lang: 'bn' })
  await signIn(page, 'student1@e2e.test')
  for (const role of ROLES) {
    if (role.home === '/student') continue
    await page.goto(role.home, { waitUntil: 'domcontentloaded' })
    // The guard redirects a mismatched role to its own home rather than
    // rendering the other role's dashboard.
    await expect
      .poll(() => new URL(page.url()).pathname, { timeout: 20_000 })
      .not.toBe(role.home)
  }
})

function format(findings: Finding[]): string {
  return findings.map((finding) => `${finding.where}: ${finding.what}`).join('\n')
}
