import { expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

/**
 * Shared plumbing for the browser accessibility sweep (AUD-G-10 / G-10, G-11).
 *
 * The unit suite already runs axe in jsdom (`src/test/axeSweep.test.tsx`),
 * with two documented blind spots: jsdom has no layout, so colour contrast
 * cannot be evaluated, and it renders single components, not routed pages
 * with the shell, the theme and the language switch applied. This helper
 * drives the built app in Chromium instead.
 */

export const THEMES = ['light', 'dark'] as const
export const LANGS = ['bn', 'en'] as const

export type Theme = (typeof THEMES)[number]
export type Lang = (typeof LANGS)[number]
export interface Variant {
  theme: Theme
  lang: Lang
}

/** The four combinations G-10 asks for: light/dark x bn/en. */
export const VARIANTS: Variant[] = THEMES.flatMap((theme) => LANGS.map((lang) => ({ theme, lang })))

export function label(variant: Variant): string {
  return `${variant.theme}-${variant.lang}`
}

/**
 * Pin the persisted theme and language before the app boots. `theme-boot.js`
 * reads both from localStorage at document start, so this is the same switch
 * a real user flips in the settings menu -- no test-only rendering path.
 */
export async function useVariant(page: Page, variant: Variant): Promise<void> {
  await page.addInitScript(
    ([theme, lang]) => {
      window.localStorage.setItem('bgpt_theme', theme)
      window.localStorage.setItem('bgpt_lang', lang)
    },
    [variant.theme, variant.lang] as const,
  )
}

export const PASSWORD = 'E2ePass!2345'

/**
 * The tutor composer's accessible name (bn and en), for specs that type into
 * it. The tutor page also renders the history search box *before* the
 * composer, so `getByRole('textbox').first()` silently resolved to the search
 * input: the typed text never reached the composer, the send button stayed
 * `disabled`, and the spec timed out (found by VA2 while re-running the
 * screen-reader spec).
 */
export const COMPOSER_LABEL = /পাঠ্যবই থেকে যেকোনো প্রশ্ন লিখুন|Ask anything from your textbook/

export async function signIn(page: Page, email: string): Promise<void> {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.locator('#email').fill(email)
  await page.locator('#password').fill(PASSWORD)
  await page.locator('form button[type="submit"]').click()
  // 60s, not the suite's 20s: the whole stack shares one machine in some
  // runs, and a slow /auth/login under load is not a login failure.
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 60_000 })
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem('bgpt_token')))
    .toBeTruthy()
}

/**
 * Navigate and settle: the React root has painted real content, webfonts are
 * loaded (the layout of Bangla text depends on them) and, best-effort, the
 * data fetches have finished so axe sees the rows and cards a user sees.
 * `networkidle` is best-effort because the tutor page keeps an SSE connection
 * open while an answer streams; it is not used as the sole readiness signal.
 *
 * The readiness landmark is `#root > *`, not `<main>`: this branch's public
 * and staff pages (login, register, parent, admin, status, legal) render
 * their own layouts without a main landmark -- only the student/teacher
 * pages carry `<main className="shell-main">`. Waiting for main would hang
 * the sweep on every public route.
 */
export async function openRoute(page: Page, route: string): Promise<void> {
  await page.goto(route, { waitUntil: 'domcontentloaded' })
  await page.locator('#root > *').first().waitFor({ state: 'attached' })
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => undefined)
  await page.evaluate(() => document.fonts.ready).catch(() => undefined)
}

export interface AxeFinding {
  route: string
  variant: string
  id: string
  impact: string
  nodes: number
  targets: string[]
}

/**
 * Run axe with the WCAG A/AA tag set (2.0, 2.1 and 2.2) and return only
 * serious/critical violations -- the G-10 bar is zero of those. Moderate and
 * minor findings are reported separately by the caller so they cannot hide.
 */
export async function axeRoute(
  page: Page,
  route: string,
  variant: Variant,
): Promise<{ blocking: AxeFinding[]; advisory: AxeFinding[] }> {
  await openRoute(page, route)
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze()
  const toFinding = (violation: (typeof results.violations)[number]): AxeFinding => ({
    route,
    variant: label(variant),
    id: violation.id,
    impact: violation.impact ?? 'unknown',
    nodes: violation.nodes.length,
    targets: violation.nodes.slice(0, 3).map((node) => node.target.join(' ')),
  })
  return {
    blocking: results.violations
      .filter((v) => v.impact === 'serious' || v.impact === 'critical')
      .map(toFinding),
    advisory: results.violations
      .filter((v) => v.impact !== 'serious' && v.impact !== 'critical')
      .map(toFinding),
  }
}

export function describeFindings(findings: AxeFinding[]): string {
  return findings
    .map(
      (f) =>
        `${f.variant} ${f.route}: ${f.id} (${f.impact}, ${f.nodes} node(s)) ${f.targets.join(' | ')}`,
    )
    .join('\n')
}
