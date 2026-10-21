import { expect, test } from '@playwright/test'
import { openRoute, signIn, useVariant } from './a11y'

/**
 * AUD-G-17 / G-17: the PWA offline shell, verified in the browser rather than
 * by reading `public/sw.js`.
 *
 * The rest of the e2e suite blocks service workers on purpose (a stale cache
 * must never mask a regression in a normal test), so this file opts back in
 * per-file. The build under test is the production bundle — `vite preview`
 * serves `dist/`, and `main.tsx` registers the worker only in a production
 * build, so this fail-fast test is also the check that the registration is
 * still wired.
 *
 * What is proven:
 *   * the worker installs and takes control;
 *   * a navigation while offline is served from the cache (the app shell
 *     renders instead of the browser's dinosaur);
 *   * API responses are never cached (a stale answer is worse than an error).
 */

test.use({ serviceWorkers: 'allow' })

test.describe.configure({ timeout: 5 * 60_000 })

test('the service worker installs, caches the hashed bundle, and boots offline', async ({
  page,
  context,
}) => {
  await useVariant(page, { theme: 'light', lang: 'bn' })
  await openRoute(page, '/welcome')

  // Registration is in main.tsx behind `import.meta.env.PROD`.
  const controlled = await page.evaluate(async () => {
    if (!('serviceWorker' in navigator)) return 'no-serviceWorker'
    const registration = await navigator.serviceWorker.ready
    return registration.active ? 'active' : 'registered-but-inactive'
  })
  expect(controlled).toBe('active')

  // A signed-in user, so the offline case exercises the guarded route.
  await signIn(page, 'student2@e2e.test')

  // Install caches the shell; the app's JS only arrives later unless the
  // worker warms the hashed assets out of index.html. Assert it did: without
  // this, "offline" is an HTML page that boots no React at all.
  const cachedAssets = await page.evaluate(async () => {
    const cache = await caches.open('bgpt-v2')
    const keys = await cache.keys()
    return keys.filter((request) => new URL(request.url).pathname.startsWith('/assets/')).length
  })
  expect(cachedAssets, 'the service worker cached no /assets/* entry').toBeGreaterThan(0)

  await context.setOffline(true)
  // Reload the guarded route while offline: the document comes from the cache
  // and the app must actually boot from the cached bundle.
  await page.goto('/student', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('main, [role="main"]')).toHaveCount(1, { timeout: 30_000 })
  // The API is unreachable, so the session screen says exactly that instead of
  // showing a dashboard of zeros (F-107) or the browser's error page.
  await expect(page.locator('body')).toContainText(/সংযোগ|connection|backend|রিট্রাই|retry/i, {
    timeout: 30_000,
  })
  await page.screenshot({ path: 'coverage/state-matrix/pwa-offline-shell.png', fullPage: true })
  await context.setOffline(false)
})

test('API responses are never served from the cache', async ({ page }) => {
  await useVariant(page, { theme: 'light', lang: 'bn' })
  await openRoute(page, '/welcome')
  await page.evaluate(async () => {
    if ('serviceWorker' in navigator) await navigator.serviceWorker.ready
  })
  const cached = await page.evaluate(async () => {
    const names = await caches.keys()
    const hits: string[] = []
    for (const name of names) {
      const cache = await caches.open(name)
      for (const request of await cache.keys()) {
        if (new URL(request.url).pathname.startsWith('/api/')) hits.push(request.url)
      }
    }
    return hits
  })
  expect(cached).toEqual([])
})
