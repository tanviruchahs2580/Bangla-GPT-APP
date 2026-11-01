import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { COMPOSER_LABEL, openRoute, signIn, useVariant } from './a11y'

/**
 * Wave-2 accessibility execution (A11Y-07's executable parts) and the FE-15
 * console guard on the routes this file touches.
 *
 * A11Y-05 stays BLOCKED for the reason screen-reader.spec.ts records: there is
 * no automatable screen reader on this host (no way to capture what Narator
 * says, no headless driver). A11Y-07 asks for the parts that ARE executable:
 * the reader's text-to-speech control must expose an accessible name and a
 * pressed state, every rendered image must carry an alt attribute, and the
 * PDF tagging question is answered by the render probe recorded with this
 * round (fpdf2 emits no structure tree; the best-effort clause applies).
 *
 * TEST-10: the axe assertion below is the same WCAG A/AA tag set the full
 * sweep uses, applied to the two interactive routes this stream owns, and it
 * fails on serious/critical violations only -- moderate/minor stay visible in
 * the full sweep's report rather than here.
 */

type ConsoleFinding = { where: string; what: string }

function watchConsole(page: Page): ConsoleFinding[] {
  const findings: ConsoleFinding[] = []
  page.on('pageerror', (error) => findings.push({ where: 'pageerror', what: error.message }))
  page.on('console', (message) => {
    if (message.type() !== 'error') return
    const text = message.text()
    if (/Failed to load resource|net::ERR_INTERNET_DISCONNECTED|net::ERR_ABORTED/.test(text)) return
    findings.push({ where: 'console.error', what: text.slice(0, 300) })
  })
  return findings
}

function expectCleanConsole(findings: ConsoleFinding[]): void {
  expect(
    findings,
    `console errors:\n${findings.map((f) => `${f.where}: ${f.what}`).join('\n')}`,
  ).toEqual([])
}

test.describe.configure({ timeout: 5 * 60_000 })

test('reader TTS control is named and exposes its pressed state', async ({ page }) => {
  const findings = watchConsole(page)
  await useVariant(page, { theme: 'light', lang: 'bn' })
  await signIn(page, 'student1@e2e.test')
  await openRoute(page, '/student/learn/science/%E0%A6%95%E0%A7%8B%E0%A6%B7')

  const listen = page.getByRole('button', { name: /শুনুন|Listen/ }).first()
  await expect(listen).toBeVisible({ timeout: 30_000 })
  await expect(listen).toHaveAttribute('aria-pressed', 'false')
  // The control a screen reader announces carries a name in the active
  // language, not an icon-only button.
  const name = await listen.evaluate((element) => element.getAttribute('aria-label'))
  expect(name && name.trim().length > 0, 'TTS control has no accessible name').toBeTruthy()

  // The same contract for the other reader controls this page exposes.
  for (const label of [/বুকমার্ক|Bookmark/, /ডাউনলোড করুন|Download chapter/]) {
    const control = page.getByRole('button', { name: label }).first()
    await expect(control).toBeVisible()
    await expect(control).toHaveAttribute('aria-pressed', /true|false/)
  }
  expectCleanConsole(findings)
})

test('every rendered image carries an alt attribute on the key routes', async ({ page }) => {
  const findings = watchConsole(page)
  await useVariant(page, { theme: 'light', lang: 'bn' })

  const check = async (route: string): Promise<void> => {
    await openRoute(page, route)
    const missing = await page.evaluate(() =>
      Array.from(document.querySelectorAll('img'))
        .filter((img) => img.getAttribute('alt') === null)
        .map((img) => img.getAttribute('src') ?? '(inline)'),
    )
    expect(missing, `${route}: image(s) without alt: ${missing.join(', ')}`).toEqual([])
  }

  await check('/')
  await check('/login')
  await signIn(page, 'student1@e2e.test')
  await check('/student/home')
  await check('/student/learn')
  await check('/student/tutor')
  expectCleanConsole(findings)
})

test('axe: zero serious/critical violations on the reader and tutor routes', async ({ page }) => {
  const findings = watchConsole(page)
  await useVariant(page, { theme: 'light', lang: 'bn' })
  await signIn(page, 'student1@e2e.test')

  const sweep = async (route: string): Promise<void> => {
    await openRoute(page, route)
    // The tutor route keeps an SSE stream open while nothing is asked, so
    // settle on the composer instead of networkidle.
    if (route.includes('tutor')) {
      await expect(page.getByLabel(COMPOSER_LABEL)).toBeVisible({ timeout: 30_000 })
    }
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze()
    const blocking = results.violations.filter(
      (violation) => violation.impact === 'serious' || violation.impact === 'critical',
    )
    const detail = blocking
      .map(
        (violation) =>
          `${route}: ${violation.id} (${violation.impact}) on ${violation.nodes
            .slice(0, 3)
            .map((node) => node.target.join(' '))
            .join(' | ')}`,
      )
      .join('\n')
    expect(blocking, `serious/critical axe violations:\n${detail}`).toEqual([])
  }

  await sweep('/student/learn/science/%E0%A6%95%E0%A7%8B%E0%A6%B7')
  await sweep('/student/tutor')
  expectCleanConsole(findings)
})
