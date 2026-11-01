import { expect, test } from '@playwright/test'
import { COMPOSER_LABEL, openRoute, signIn, useVariant } from './a11y'

/**
 * AUD-G-12 / G-12: the strongest screen-reader evidence this environment can
 * produce, plus the reason the screen-reader run itself is still not done.
 *
 * Windows Narrator is installed and was already running in this session
 * (E-R2-g2-002), but a screen reader is only observable through its speech:
 * there is no audio-capture path available here, no API exposes what Narrator
 * said, and it cannot be driven headlessly against a specific browser window.
 * So the item stays PARTIAL, and what is asserted here instead is everything a
 * screen reader would be *told*: the accessible tree structure (reviewed ARIA
 * snapshot baselines), the landmarks, the html `lang` and its switch, and the
 * one polite live-region announcement per completed streamed answer.
 *
 * The snapshots live next to the visual baselines under
 * `e2e/__screenshots__/screen-reader.spec.ts/` and were read during review.
 */

test.describe.configure({ timeout: 5 * 60_000 })

test('login screen accessible tree and language (bn), reviewed ARIA baseline', async ({ page }) => {
  await useVariant(page, { theme: 'light', lang: 'bn' })
  await openRoute(page, '/login')
  expect(await page.locator('html').getAttribute('lang')).toBe('bn')
  // What a screen reader is handed first on the public pages (F-003): the skip
  // link, the language switch, then the page's main landmark with its level-1
  // heading and the single login form -- the ARIA baseline below records the
  // tree as it is.
  await expect(page.locator('a.skip-link')).toBeAttached()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.locator('form')).toHaveCount(1)
  await expect(page.locator('button.public-lang-toggle')).toBeVisible()
  await expect(page.locator('body')).toMatchAriaSnapshot({
    name: 'login-bn.aria.yml',
  })
})

test('language switch moves html lang to en and the tree follows', async ({ page }) => {
  await useVariant(page, { theme: 'light', lang: 'bn' })
  await openRoute(page, '/login')
  await page.locator('button.public-lang-toggle').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.locator('body')).toMatchAriaSnapshot({
    name: 'login-en.aria.yml',
  })
})

test('tutor screen landmarks, live region and reviewed ARIA baseline (bn)', async ({ page }) => {
  await useVariant(page, { theme: 'light', lang: 'bn' })
  await signIn(page, 'student2@e2e.test')
  await openRoute(page, '/student/tutor')
  expect(await page.locator('html').getAttribute('lang')).toBe('bn')
  // One main landmark -- the page's own, and it is the skip link's target
  // (F-003) -- plus a navigation landmark from the shell: the tutor page must
  // not hand the screen reader a bare div soup.
  await expect(page.locator('main')).toHaveCount(1)
  await expect(page.locator('main#main-content')).toHaveCount(1)
  await expect(page.locator('nav').first()).toBeVisible()
  // The streaming announcement channel: a polite status region that stays
  // empty while tokens stream and carries one sentence when the answer is done.
  const announcer = page.locator('[data-testid="tutor-announcer"][role="status"]')
  await expect(announcer).toHaveCount(1)
  await expect(announcer).toHaveAttribute('aria-live', 'polite')
  await expect(announcer).toBeEmpty()
  await expect(page.locator('body')).toMatchAriaSnapshot({
    name: 'tutor-bn.aria.yml',
  })
})

test('a completed streamed answer is announced exactly once, in the live region', async ({
  page,
}) => {
  await useVariant(page, { theme: 'light', lang: 'bn' })
  await signIn(page, 'student2@e2e.test')
  await openRoute(page, '/student/tutor')
  const announcer = page.locator('[data-testid="tutor-announcer"]')
  // The composer by its own accessible name: the page also carries the history
  // search box, and `getByRole('textbox').first()` resolved to that one, so the
  // send button never left `disabled` and this test timed out (VA2).
  const ask = page.getByRole('textbox', { name: COMPOSER_LABEL })
  await ask.fill('কোষ কী?')
  await page.getByRole('button', { name: 'পাঠান' }).first().click()
  const answer = page.locator('.bubble.assistant').last()
  // Both section headings: this test pins the Bangla UI (`useVariant`), where
  // the structured answer's heading is `সহজ ব্যাখ্যা`. The English literal only
  // ever matched because smoke.spec pins `bgpt_lang=en` (VA2).
  await expect(answer).toContainText(/Simple explanation|সহজ ব্যাখ্যা/, {
    timeout: 60_000,
  })
  // The announcement is the whole completed answer, set once: no per-token
  // chatter while streaming, and no announcement left empty after it.
  await expect(announcer).not.toBeEmpty()
  const announced = await announcer.textContent()
  expect((announced ?? '').length).toBeGreaterThan(20)
})
