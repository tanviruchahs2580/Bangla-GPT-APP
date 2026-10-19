import { expect, test, type Page } from '@playwright/test'
import { signIn, useVariant } from './a11y'

/**
 * AUD-G-19 / G-19: low-end-device behaviour. Chromium's CPU throttling emulates
 * a 4-6x slower main thread; PerformanceObserver('longtask') records every
 * task the renderer ran. The bar is the one the finding names: no main-thread
 * block longer than 100 ms.
 *
 * Two surfaces carry the risk:
 *
 *  1. the tutor thread with a long history -- `seed_long_history.py` seeds 120
 *     real-shaped Bangla messages (200 is the API's per-fetch cap), rendered
 *     as one list, then an answer streams over SSE;
 *  2. a maximal CSV roster import -- 200 rows, `IMPORT_MAX_ROWS`'s documented
 *     ceiling, so this is the largest import the product accepts.
 *
 * Traces are written under `coverage/perf/` (gitignored); the measurements
 * themselves are asserted here so the numbers cannot rot.
 */

const LONG_HISTORY_TITLE = 'E2E long history'

interface Task {
  start: number
  duration: number
}

interface Probe {
  tasks: Task[]
  marks: { name: string; at: number }[]
}

async function installLongTaskProbe(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const probe = window as unknown as {
      __longTasks: { start: number; duration: number }[]
      __marks: { name: string; at: number }[]
    }
    probe.__longTasks = []
    probe.__marks = []
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        probe.__longTasks.push({
          start: Math.round(entry.startTime),
          duration: Math.round(entry.duration),
        })
      }
    }).observe({ entryTypes: ['longtask'] })
  })
}

async function mark(page: Page, name: string): Promise<void> {
  await page.evaluate((label) => {
    const probe = window as unknown as {
      __marks: { name: string; at: number }[]
    }
    probe.__marks.push({ name: label, at: Math.round(performance.now()) })
  }, name)
}

async function probe(page: Page): Promise<Probe> {
  return page.evaluate(() => {
    const store = window as unknown as {
      __longTasks: Task[]
      __marks: Probe['marks']
    }
    return { tasks: store.__longTasks, marks: store.__marks }
  })
}

function describeTasks(tasks: Task[], marks: Probe['marks']): string {
  const phase = (start: number): string => {
    let current = 'before-first-mark'
    for (const entry of marks) if (entry.at <= start) current = entry.name
    return current
  }
  return tasks
    .filter((task) => task.duration > 100)
    .map((task) => `${task.duration}ms at ${task.start}ms during ${phase(task.start)}`)
    .join('; ')
}

test.describe.configure({ timeout: 8 * 60_000 })

test('tutor thread with 120 messages streams a new answer at 4x CPU throttle', async ({
  page,
  context,
}) => {
  await useVariant(page, { theme: 'light', lang: 'bn' })
  const cdp = await context.newCDPSession(page)
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 })
  await installLongTaskProbe(page)
  // Tracing is already started by playwright.config.ts (trace:
  // 'retain-on-failure'); starting it twice throws. We only redirect the
  // stop() to a named file so the throttle trace is kept even on success.
  await signIn(page, 'student1@e2e.test')
  await page.goto('/student/tutor', { waitUntil: 'domcontentloaded' })
  await mark(page, 'tutor-route-loaded')

  const history = page.getByRole('button', { name: new RegExp(LONG_HISTORY_TITLE) }).first()
  await expect(history).toBeVisible()
  await history.click()
  await expect(page.locator('.bubble.assistant').first()).toBeVisible({
    timeout: 60_000,
  })
  await mark(page, 'history-rendered')

  const bubbleCount = await page.locator('.bubble').count()
  expect(bubbleCount).toBeGreaterThan(100)

  const ask = page.getByRole('textbox').first()
  await ask.fill('আরেকবার বুঝিয়ে দাও')
  await mark(page, 'question-typed')
  await page
    .getByRole('button', { name: /Send|পাঠান/ })
    .first()
    .click()
  await expect(page.locator('.bubble.assistant').last()).toContainText(/Simple explanation|সহজ/, {
    timeout: 90_000,
  })
  await mark(page, 'answer-streamed')

  const measured = await probe(page)
  await context.tracing.stop({ path: 'coverage/perf/tutor-4x-trace.zip' })
  console.log(
    `long tasks: ${measured.tasks.length}; total ${measured.tasks.reduce((sum, t) => sum + t.duration, 0)}ms; worst ${Math.max(0, ...measured.tasks.map((t) => t.duration))}ms`,
  )
  expect(describeTasks(measured.tasks, measured.marks)).toBe('')
})

test('maximal roster CSV import (200 rows) at 4x CPU throttle', async ({ page, context }) => {
  await useVariant(page, { theme: 'light', lang: 'en' })
  const cdp = await context.newCDPSession(page)
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 })
  await installLongTaskProbe(page)
  await signIn(page, 'teacher1@e2e.test')
  await page.goto('/teacher/classes', { waitUntil: 'domcontentloaded' })
  await mark(page, 'classes-route-loaded')

  // A classroom has to exist before the import card renders. The create form
  // is only in the tree while the list is empty, so a repeated run simply
  // reuses the room the first run created.
  const csvCard = page.getByText('Add students from CSV')
  if (!(await csvCard.isVisible().catch(() => false))) {
    await page.locator('#nsec').fill('P4')
    await page.locator('form button[type="submit"]').first().click()
    await expect(csvCard).toBeVisible({ timeout: 30_000 })
  }
  await mark(page, 'import-card-ready')

  const run = Date.now()
  const rows = ['name,email']
  for (let index = 0; index < 200; index += 1) {
    rows.push(`পরীক্ষা শিক্ষার্থী ${index + 1},perf-${run}-${index}@example.test`)
  }
  const csv = rows.join('\n')
  expect(csv.length).toBeLessThan(20_000) // the API's own bound

  const textarea = page.locator('textarea.textarea')
  await textarea.fill(csv)
  await mark(page, 'csv-pasted')
  await page
    .getByRole('button', { name: /Import|ইমপোর্ট/ })
    .first()
    .click()
  await expect(page.getByText('Created: 200')).toBeVisible({
    timeout: 180_000,
  })
  await mark(page, 'import-finished')

  const measured = await probe(page)
  await context.tracing.stop({ path: 'coverage/perf/csv-4x-trace.zip' })
  console.log(
    `long tasks: ${measured.tasks.length}; total ${measured.tasks.reduce((sum, t) => sum + t.duration, 0)}ms; worst ${Math.max(0, ...measured.tasks.map((t) => t.duration))}ms`,
  )
  expect(describeTasks(measured.tasks, measured.marks)).toBe('')
})

test('tutor history renders at 6x CPU throttle without a >100 ms task', async ({
  page,
  context,
}) => {
  await useVariant(page, { theme: 'light', lang: 'bn' })
  const cdp = await context.newCDPSession(page)
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 6 })
  await installLongTaskProbe(page)
  await signIn(page, 'student1@e2e.test')
  await page.goto('/student/tutor', { waitUntil: 'domcontentloaded' })
  const history = page.getByRole('button', { name: new RegExp(LONG_HISTORY_TITLE) }).first()
  await expect(history).toBeVisible()
  await mark(page, 'history-list-visible')
  await history.click()
  await expect(page.locator('.bubble.assistant').first()).toBeVisible({
    timeout: 90_000,
  })
  await mark(page, 'history-rendered')
  const measured = await probe(page)
  await context.tracing.stop({ path: 'coverage/perf/tutor-6x-trace.zip' })
  console.log(
    `long tasks: ${measured.tasks.length}; total ${measured.tasks.reduce((sum, t) => sum + t.duration, 0)}ms; worst ${Math.max(0, ...measured.tasks.map((t) => t.duration))}ms`,
  )
  expect(describeTasks(measured.tasks, measured.marks)).toBe('')
})
