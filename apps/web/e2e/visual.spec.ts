import { expect, test } from '@playwright/test'
import { openRoute, signIn, useVariant, VARIANTS } from './a11y'

/**
 * AUD-G-07 / G-07 (E-13): the screenshot matrix -- key screens at 360, 768 and
 * 1280 px, in both themes and both languages -- as reviewed Playwright
 * baselines rather than one-off files under docs/.
 *
 * Determinism: the theme and language are pinned before boot (the same
 * localStorage switches a user flips), animations and transitions are
 * disabled by the screenshot comparator, webfonts are awaited, and the two
 * role screens use the *read-only* seed accounts (student2/teacher2), which
 * no test writes to -- student1/teacher1 accumulate conversations, classes
 * and roster rows, and a snapshot taken after those runs would record the
 * side effect instead of the UI.
 *
 * Review: the baselines were opened and inspected at review time, not merely
 * accepted because a first run wrote them.
 *
 * Platform note: the baselines are reviewed on the platform that generated
 * them. Text rasterisation differs between OS font stacks far beyond any
 * sane pixel tolerance (measured: the Windows-authored set failed every
 * Linux snapshot at 3-5%+ on identical commits), so the matrix runs where
 * the baselines were reviewed and skips elsewhere — the unit suite, axe
 * sweep and keyboard contracts still gate every platform.
 */
test.skip(
  process.platform !== 'win32',
  'visual baselines are reviewed against the Windows rasteriser; a Linux baseline set is a follow-up (run `npx playwright test e2e/visual.spec.ts --update-snapshots` on Linux and commit it)',
)

const VIEWPORTS = [
  { label: '360', width: 360, height: 740 },
  { label: '768', width: 768, height: 1024 },
  { label: '1280', width: 1280, height: 800 },
]

interface Screen {
  name: string
  route: string
  email?: string
  /** Pins screen state the route's own effects would otherwise leave open. */
  prepare?: (page: import('@playwright/test').Page) => Promise<void>
}

const SCREENS: Screen[] = [
  { name: 'welcome', route: '/welcome' },
  { name: 'login', route: '/login' },
  { name: 'student-home', route: '/student', email: 'student2@e2e.test' },
  {
    name: 'student-tutor',
    route: '/student/tutor',
    email: 'student2@e2e.test',
    // F-204: the tutor thread autoscrolls to its last message on mount and
    // lays out after the Bangla webfont settles, so a full-suite run measured
    // a different scroll/layout state than an isolated one (4.2% pixel delta
    // against the reviewed baselines). Pin the scroll offsets and wait for
    // fonts and pending frames before the comparator reads the page.
    prepare: async (page) => {
      await page.evaluate(() => {
        const thread = document.querySelector('.chat-viewport')
        if (thread) thread.scrollTop = 0
        window.scrollTo(0, 0)
      })
      await page.evaluate(() => document.fonts.ready)
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          ),
      )
    },
  },
  { name: 'teacher-home', route: '/teacher', email: 'teacher2@e2e.test' },
]

test.describe.configure({ timeout: 10 * 60_000 })

for (const screen of SCREENS) {
  for (const variant of VARIANTS) {
    for (const viewport of VIEWPORTS) {
      const snapshot = `${screen.name}--${variant.theme}-${variant.lang}--${viewport.label}`
      test(`visual: ${snapshot}`, async ({ page }) => {
        await page.setViewportSize({
          width: viewport.width,
          height: viewport.height,
        })
        await useVariant(page, variant)
        if (screen.email) await signIn(page, screen.email)
        await openRoute(page, screen.route)
        await screen.prepare?.(page)
        // PNG: Playwright's toHaveScreenshot does not take a JPEG encoder.
        // The two screens that carry a photo background stay under the
        // repository's 512 KB per-added-file limit because the background
        // JPEGs themselves were re-encoded (AUD-G-16 in findings-g.csv).
        await expect(page).toHaveScreenshot(`${snapshot}.png`, {
          animations: 'disabled',
          caret: 'hide',
          maxDiffPixelRatio: 0.02,
        })
      })
    }
  }
}
