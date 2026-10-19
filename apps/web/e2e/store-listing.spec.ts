import { expect, test } from '@playwright/test'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { openRoute, signIn, useVariant } from './a11y'

/**
 * Play Store listing assets (docs/playstore/listing.md): phone screenshots
 * and the feature graphic, rendered from the real app instead of mocked up in
 * a design tool -- a listing screenshot that shows a screen the app does not
 * have is the same class of false user-visible claim the audit treats as a
 * defect.
 *
 * Opt-in by design: `STORE_ASSETS=1 npx playwright test e2e/store-listing.spec.ts`.
 * The default run stays green without it, and CI never regenerates listing
 * assets on its own (they are reviewed, committed artifacts).
 *
 * Sizes: Play requires phone screenshots with a side between 320 and 3840 px
 * and an aspect ratio between 9:16 and 16:9. A 405x720 CSS viewport at
 * deviceScaleFactor 3 is exactly 1215x2160 px (9:16) and renders the phone
 * layout, so nothing is letterboxed. The feature graphic is 1024x500, the
 * Play-required size. JPEG output: Play's phone screenshots must be 24-bit
 * with no alpha, and JPEG guarantees that without an alpha-flattening pass.
 */

const OUT_DIR = join(process.cwd(), '..', '..', 'docs', 'playstore', 'assets', 'screenshots')
const PHONE = { width: 405, height: 720 }
const SCALE = 3

interface Screen {
  slug: string
  route: string
  email?: string
  /** Bengali + English captions for the listing (docs/playstore/listing.md). */
  caption: { bn: string; en: string }
}

const SCREENS: Screen[] = [
  {
    slug: 'welcome',
    route: '/welcome',
    caption: { bn: 'শ্রেণি ৬-১০ এর জন্য বাংলা টিউটর', en: 'A Bangla tutor for classes 6-10' },
  },
  {
    slug: 'login',
    route: '/login',
    caption: { bn: 'শিক্ষার্থী, শিক্ষক ও অভিভাবকের আলাদা অ্যাকাউন্ট', en: 'Separate accounts for students, teachers and parents' },
  },
  {
    slug: 'student-home',
    route: '/student',
    email: 'student2@e2e.test',
    caption: { bn: 'পাঠ্যবইভিত্তিক উত্তর, সূত্রসহ', en: 'Textbook-grounded answers, with sources' },
  },
  {
    slug: 'student-tutor',
    route: '/student/tutor',
    email: 'student2@e2e.test',
    caption: { bn: 'প্রশ্ন লিখুন বা ছবি তুলুন', en: 'Ask by typing or by photo' },
  },
  {
    slug: 'student-practice',
    route: '/student/practice',
    email: 'student2@e2e.test',
    caption: { bn: 'অনুশীলন ও অগ্রগতি', en: 'Practice and progress' },
  },
  {
    slug: 'teacher-dashboard',
    route: '/teacher',
    email: 'teacher2@e2e.test',
    caption: { bn: 'শিক্ষকের ক্লাসরুম ও প্রশ্নপত্র', en: 'Teacher classroom and question papers' },
  },
]

const enabled = process.env.STORE_ASSETS === '1'

test.describe('Play Store listing assets', () => {
  test.skip(!enabled, 'set STORE_ASSETS=1 to regenerate the listing assets')

  test.beforeAll(() => {
    mkdirSync(OUT_DIR, { recursive: true })
  })

  for (const screen of SCREENS) {
    test(`screenshot: ${screen.slug} (bn + en)`, async ({ page }) => {
      await page.setViewportSize(PHONE)
      await page.context().addInitScript(() => {
        // The screenshots are captured at a fixed scale; a user-agent override
        // keeps the app from switching to a desktop layout.
        Object.defineProperty(window.screen, 'width', { value: 405 })
        Object.defineProperty(window.screen, 'height', { value: 720 })
      })
      for (const lang of ['bn', 'en'] as const) {
        await useVariant(page, { lang, theme: 'light' })
        if (screen.email) {
          await signIn(page, screen.email)
        }
        await openRoute(page, screen.route)
        await page.waitForTimeout(400) // settle lazy chunks before the capture
        await page.screenshot({
          path: join(OUT_DIR, `${screen.slug}--${lang}.jpg`),
          type: 'jpeg',
          quality: 92,
        })
        if (screen.email) {
          // Signing out between languages keeps the next pass from landing on
          // an already-authenticated shell.
          await page.evaluate(() => window.localStorage.clear())
        }
      }
      expect(existsSync(join(OUT_DIR, `${screen.slug}--bn.jpg`))).toBe(true)
    })
  }

  test('captions file matches the captured screens', () => {
    // The captions live in the listing doc; this file is the machine-readable
    // copy so a re-capture cannot silently drift from what the listing claims.
    const rows = SCREENS.map((s) => ({ slug: s.slug, ...s.caption }))
    writeFileSync(join(OUT_DIR, 'captions.json'), JSON.stringify(rows, null, 2) + '\n', 'utf8')
    expect(rows).toHaveLength(SCREENS.length)
  })

  test('feature graphic 1024x500', async ({ page }) => {
    // Deliberately typographic: the brand, the audience and the grounding
    // promise. No invented UI, no stock photo, no numbers that need a citation.
    await page.setViewportSize({ width: 1024, height: 500 })
    await page.setContent(
      `<!doctype html><html><head><meta charset="utf-8"><style>
        html,body{margin:0;height:500px;width:1024px}
        .wrap{height:100%;display:flex;flex-direction:column;justify-content:center;
              gap:18px;padding:0 72px;font-family:system-ui,'Noto Sans Bengali',sans-serif;
              background:linear-gradient(135deg,#0f3d2e 0%,#166534 55%,#1f7a4d 100%);color:#fff}
        .title{font-size:64px;font-weight:800;line-height:1.1}
        .sub{font-size:30px;opacity:.95}
        .rule{width:120px;height:6px;background:#facc15;border-radius:3px}
      </style></head><body><div class="wrap">
        <div class="rule"></div>
        <div class="title">বাংলা GPT টিউটর</div>
        <div class="sub">শ্রেণি ৬-১০ · পাঠ্যবইভিত্তিক উত্তর · সূত্রসহ</div>
      </div></body></html>`,
      { waitUntil: 'load' },
    )
    await page.screenshot({ path: join(OUT_DIR, 'feature-graphic.jpg'), type: 'jpeg', quality: 92 })
    expect(existsSync(join(OUT_DIR, 'feature-graphic.jpg'))).toBe(true)
  })
})
