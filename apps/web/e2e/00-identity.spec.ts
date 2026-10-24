import { expect, test } from '@playwright/test'

/**
 * Run-identity guard, sorts first (00-).
 *
 * Found the hard way: on a machine where port 5173 already served a DIFFERENT
 * project's dev server, `reuseExistingServer` latched onto it and the whole
 * suite axe-scanned the wrong product — the failures made no sense until the
 * page title did. Every spec navigates blindly after this one, so the check
 * lives here: if the served app is not ours, the run dies at test #1 with a
 * message that names the actual served title instead of 40 confusing
 * selector failures.
 */
test('the harness is serving THIS app', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const title = await page.title()
  expect.soft(
    title,
    `port ${process.env.E2E_WEB_PORT ?? 5173} is serving a different app ("${title}"). ` +
      'Set E2E_WEB_PORT (and E2E_API_PORT) to free ports — see playwright.config.ts.',
  ).toContain('বাংলা GPT')
})
