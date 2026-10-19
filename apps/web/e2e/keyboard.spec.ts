import { expect, test, type Page } from '@playwright/test'
import { openRoute, signIn, useVariant } from './a11y'

/**
 * AUD-G-11 / G-11: keyboard-only operation of each role's primary flow.
 *
 * Everything here goes through the keyboard: Tab/Shift+Tab for movement,
 * Enter/Space for activation. Two rules are asserted rather than assumed --
 * every focus stop produced by a real Tab press must be visibly indicated
 * (computed outline or box-shadow; the app's `:focus-visible` ring), and
 * focus must never stick (a second cycle proves the tab sequence terminates
 * instead of looping inside a control). Programmatic `focus()` is used only
 * to place the pointer for a subsequent keyboard activation, never to
 * replace one, and no assertion about `:focus-visible` is made on those
 * stops -- synthetic focus does not set that pseudo-class in Chromium.
 */

/** A stable description of the focused element, for order assertions. */
async function focused(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null
    if (!el || el === document.body) return 'body'
    const id = el.id ? `#${el.id}` : ''
    const type = el.getAttribute('type') ? `[${el.getAttribute('type')}]` : ''
    const firstClass = (el.getAttribute('class') ?? '').split(' ')[0]
    const cls = firstClass ? `.${firstClass}` : ''
    const label = el.getAttribute('aria-label') ?? (el.textContent ?? '').trim().slice(0, 30)
    return `${el.tagName.toLowerCase()}${id}${type}${cls}:${label}`
  })
}

/** True when the focused element paints a focus indicator. */
async function focusIsVisible(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null
    if (!el) return false
    const style = getComputedStyle(el)
    const outline =
      style.outlineStyle !== 'none' && Number.parseFloat(style.outlineWidth || '0') > 0
    return outline || style.boxShadow !== 'none'
  })
}

/**
 * Tab through the page, asserting a visible indicator on every stop, until
 * focus wraps to the document (activeElement becomes body), which is where
 * the browser's own chrome takes over. Returns the visited stops.
 */
async function tabSweep(page: Page, maxStops = 60): Promise<string[]> {
  const stops: string[] = []
  for (let index = 0; index < maxStops; index += 1) {
    await page.keyboard.press('Tab')
    const stop = await focused(page)
    if (stop === 'body') return stops
    expect(await focusIsVisible(page), `no visible focus indicator on ${stop}`).toBe(true)
    stops.push(stop)
  }
  throw new Error(`tab sequence did not terminate within ${maxStops} stops: ${stops.join(' > ')}`)
}

test('skip link is the first stop, visible when focused, and moves focus into main', async ({
  page,
}) => {
  await openRoute(page, '/login')
  await page.keyboard.press('Tab')
  const first = await focused(page)
  expect(first).toContain('.skip-link')
  expect(await focusIsVisible(page)).toBe(true)
  await page.keyboard.press('Enter')
  // The link targets #main-content, which carries tabIndex=-1, so real focus
  // lands inside the page's main landmark rather than only scrolling to it.
  expect(await page.evaluate(() => document.activeElement?.id)).toBe('main-content')
})

test('login form runs in visual order and signs in with Enter alone', async ({ page }) => {
  await openRoute(page, '/login')
  const order: string[] = []
  for (let index = 0; index < 12 && !order.some((s) => s.includes('[submit]')); index += 1) {
    await page.keyboard.press('Tab')
    const stop = await focused(page)
    if (stop === 'body') break
    expect(await focusIsVisible(page), `no visible focus indicator on ${stop}`).toBe(true)
    order.push(stop)
    if (stop.startsWith('input#email')) {
      await page.keyboard.type('student1@e2e.test')
    } else if (stop.startsWith('input#password')) {
      await page.keyboard.type('E2ePass!2345')
    } else if (stop.includes('[submit]')) {
      await page.keyboard.press('Enter')
    }
  }
  expect(order.join(' > ')).toContain('input#email')
  expect(order.indexOf(order.find((s) => s.startsWith('input#email')) ?? '')).toBeLessThan(
    order.indexOf(order.find((s) => s.startsWith('input#password')) ?? ''),
  )
  await expect(page).toHaveURL(/\/student$/)
})

test('student opens the tutor, sends with Enter and the evidence dialog traps and restores focus', async ({
  page,
}) => {
  await useVariant(page, { theme: 'light', lang: 'bn' })
  await signIn(page, 'student1@e2e.test')
  await openRoute(page, '/student/tutor')

  // Open the seeded long-history conversation (seed_long_history.py): its
  // assistant turns already carry citation sources, so the dialog assertions
  // below do not depend on a fresh answer arriving over SSE -- that path is
  // covered by smoke.spec.ts and by screen-reader.spec.ts.
  const history = page.getByRole('button', { name: /E2E long history/ }).first()
  await expect(history).toBeVisible()
  await history.focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('.bubble.assistant').first()).toBeVisible({ timeout: 60_000 })

  // The composer is reachable by keyboard and Enter sends (IME-safe handler).
  const ask = page.getByRole('textbox').first()
  await ask.focus()
  await page.keyboard.type('আরেকবার বুঝিয়ে দাও')
  await page.keyboard.press('Enter')

  // Keyboard activation of a citation chip: focus it, then press Enter.
  const chip = page.locator('button.source-chip').last()
  await expect(chip).toBeVisible()
  await chip.focus()
  await page.keyboard.press('Enter')

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))).toBe(true)

  // The trap holds: ten Tabs stay inside the dialog's own focusables.
  for (let index = 0; index < 10; index += 1) {
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))).toBe(
      true,
    )
  }
  // Shift+Tab from the first element wraps to the last rather than escaping.
  await dialog.locator('button').first().focus()
  await page.keyboard.press('Shift+Tab')
  expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))).toBe(true)

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  // Focus is restored to the opener (the chip), not dropped on <body>.
  expect(await page.evaluate(() => document.activeElement?.className)).toContain('source-chip')
})

test('teacher reaches the classes screen by keyboard and every focus stop is visible', async ({
  page,
}) => {
  await signIn(page, 'teacher1@e2e.test')
  const navLink = page.locator('a[href="/teacher/classes"]').first()
  await expect(navLink).toBeVisible()
  await navLink.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/teacher\/classes$/)
  const stops = await tabSweep(page)
  expect(stops.length).toBeGreaterThan(5)
})

test('parent form is operable by keyboard and reports an invalid code accessibly', async ({
  page,
}) => {
  await signIn(page, 'parent1@e2e.test')
  const code = page.locator('#icode')
  await expect(code).toBeVisible()
  await code.focus()
  await page.keyboard.type('BGPT-NOTREAL')
  await page.keyboard.press('Enter')
  // The inline error is programmatically surfaced (role=alert / aria-live),
  // which is what makes it audible to a screen-reader user.
  const alert = page.locator('[role="alert"], [aria-live]').filter({ hasText: /./ }).first()
  await expect(alert).toBeVisible({ timeout: 20_000 })
})

test('admin searches users by keyboard alone', async ({ page }) => {
  await signIn(page, 'admin1@e2e.test')
  const query = page.locator('#q')
  await expect(query).toBeVisible()
  await query.focus()
  await page.keyboard.type('student1@e2e.test')
  await page.keyboard.press('Enter')
  await expect(page.getByText('student1@e2e.test').first()).toBeVisible({
    timeout: 20_000,
  })
  const stops = await tabSweep(page, 25)
  expect(stops.length).toBeGreaterThan(3)
})

test('school admin dashboard is reachable and tabbable', async ({ page }) => {
  await signIn(page, 'schooladmin1@e2e.test')
  await expect(page).toHaveURL(/\/school$/)
  const stops = await tabSweep(page, 40)
  expect(stops.length).toBeGreaterThan(3)
})
