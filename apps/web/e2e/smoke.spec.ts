import { expect, test, type Page } from '@playwright/test'

/**
 * AUD-EF-02 / E-10 (issue #38): the critical user journeys, in a real browser.
 *
 * Every test drives the shipped UI against the real API (mock LLM provider,
 * seeded role accounts -- see seed_e2e_users.py). If a route guard, the auth
 * flow, the /api proxy, the invite-code flow or a dashboard's first data fetch
 * breaks, one of these fails. No fixed sleeps: everything waits on a real
 * signal (URL, visible bubble, table cell) via Playwright's auto-waiting.
 */

const PASSWORD = 'E2ePass!2345'
const STUDENT = 'student1@e2e.test'
const TEACHER = 'teacher1@e2e.test'
const PARENT = 'parent1@e2e.test'
const ADMIN = 'admin1@e2e.test'

// The app defaults to Bangla; pin English so the selectors below are stable
// and a missing translation key still renders (i18n is covered by unit tests).
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem('bgpt_lang', 'en'))
})

// `load` also waits for the font files; `domcontentloaded` is enough for the
// React mount, and every assertion below waits on a real DOM signal anyway.
async function open(page: Page, path: string): Promise<void> {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

async function signIn(page: Page, email: string): Promise<void> {
  await open(page, '/login')
  await page.locator('#email').fill(email)
  await page.locator('#password').fill(PASSWORD)
  await page.locator('form button[type="submit"]').click()
  // Wait for the SESSION, not just the click. The role router leaves /login
  // only after the token is stored; a test that navigates in the gap gets
  // bounced by the auth guard -- the parent-invite journey raced exactly
  // there in the first CI run of this suite (/login snapshot after signIn).
  await expect(page).not.toHaveURL(/\/login$/)
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem('bgpt_token')))
    .toBeTruthy()
}

async function signOut(page: Page): Promise<void> {
  // Scoped to the header: MePage also carries a labelled "Log out" button, so
  // a page-wide role query is ambiguous (strict-mode violation) on that route.
  await page.locator('header').getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)
}

test('a student signs in, is routed to the student home and can log out', async ({ page }) => {
  await signIn(page, STUDENT)

  // Role-based landing page, not just "login returned 200".
  await expect(page).toHaveURL(/\/student$/)
  expect(await page.evaluate(() => window.localStorage.getItem('bgpt_token'))).toBeTruthy()

  await signOut(page)
  // Sign-out must wipe the shared-device token, not only navigate.
  expect(await page.evaluate(() => window.localStorage.getItem('bgpt_token'))).toBeNull()
  // AppShell is gone: the login form is reachable again.
  await expect(page.locator('#email')).toBeVisible()
})

test('a student asks the tutor and gets a streamed mock answer', async ({ page }) => {
  await signIn(page, STUDENT)
  await expect(page).toHaveURL(/\/student$/)

  await open(page, '/student/tutor')
  const ask = page.getByRole('textbox', { name: 'Ask anything from your textbook…' })
  await ask.fill('কোষ কী?')
  await page.getByRole('button', { name: 'Send' }).click()

  // The answer arrives over SSE. The mock provider prefixes grounded answers
  // with "[mock]" and quotes retrieved textbook text, so this asserts that the
  // stream completed AND that retrieval found evidence for the question.
  // The mock provider renders the four-section teaching layout from the
  // retrieved textbook sentences, so this asserts the stream completed, the
  // sectioned answer rendered AND retrieval surfaced real science text about
  // the cell under test (the question was "কোষ কী?" -- what is a cell?).
  const answer = page.locator('.bubble.assistant').last()
  await expect(answer).toContainText('Simple explanation', { timeout: 60_000 })
  await expect(answer).toContainText('কোষ')
})

test('a teacher signs in and sees the teacher dashboard', async ({ page }) => {
  await signIn(page, TEACHER)

  await expect(page).toHaveURL(/\/teacher$/)
  await expect(page.getByText('Teacher dashboard')).toBeVisible()
  // The dashboard's own data fetch resolved (stats card, not a permanent
  // "loading" skeleton): the greeting is rendered from /users/me.
  await expect(page.locator('h2').first()).toContainText('E2E Teacher')
})

test('a student generates a parent invite code and the parent links with it', async ({
  page,
}) => {
  // Student side: the code is a real product feature in MePage.
  await signIn(page, STUDENT)
  await open(page, '/student/me')
  await page.getByRole('button', { name: 'Generate code' }).click()
  const code = (await page.locator('.invite-code').textContent())?.trim() ?? ''
  expect(code).toMatch(/^BGPT-[A-Z0-9]+$/)

  await signOut(page)

  // Parent side: redeem the code in the parent dashboard.
  await signIn(page, PARENT)
  await expect(page).toHaveURL(/\/parent$/)
  await page.locator('#icode').fill(code)
  await page.getByRole('button', { name: 'Link' }).click()

  await expect(page.getByText("Linked to your child's account.")).toBeVisible()
  // The children table is fed by /parents/me/children: the link is real.
  const row = page.locator('table tbody tr', { hasText: 'E2E Student' })
  await expect(row).toHaveCount(1)
})

test('an admin signs in and sees the admin dashboard', async ({ page }) => {
  await signIn(page, ADMIN)

  await expect(page).toHaveURL(/\/admin$/)
  await expect(page.getByRole('heading', { name: 'Admin dashboard' }).first()).toBeVisible()
})
