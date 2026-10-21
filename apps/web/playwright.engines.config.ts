import { defineConfig, devices } from '@playwright/test'
import base from './playwright.config'

/**
 * The three-engine pass for the Bangla item family (G-21, G-22): the same
 * checks in Chromium, Firefox and WebKit.
 *
 * It is a *separate* config on purpose. `playwright.config.ts` ships exactly
 * one Chromium project because the per-PR e2e job installs only Chromium;
 * adding Firefox and WebKit there would make that job fail with "browser not
 * installed" instead of testing anything. This config reuses every other
 * setting (servers, seeding, timeouts, reporters) and only widens the browser
 * matrix, so it runs on the nightly schedule or on demand:
 *
 *     npx playwright test -c playwright.engines.config.ts
 *
 * The web/mobile-engine claim in the item is only half covered here: WebKit
 * under Playwright's Desktop Safari device is not an iOS device, and this host
 * has no Android device attached. The handoff records the residual.
 */
export default defineConfig({
  ...base,
  testMatch: /engines\.spec\.ts/,
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
})
