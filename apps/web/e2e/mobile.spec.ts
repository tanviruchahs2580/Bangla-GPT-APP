import { expect, test } from "@playwright/test";
import { COMPOSER_LABEL, openRoute, signIn, useVariant } from "./a11y";

/**
 * FE-18 / UX-09: the mobile device profile. The audit found the e2e matrix had
 * no device profile at all, so touch-target sizes, the bottom navigation and
 * the mobile layout were reviewed in code and throttled CPU runs only. This
 * file runs under the `mobile-chromium` project (Pixel 5, 393x851, touch) on
 * the same real API as the rest of the suite.
 *
 * Two things are checked here that a desktop viewport cannot show:
 *   * the bottom navigation is the primary nav, and every one of its targets
 *     meets the 44px minimum (UX-09);
 *   * the student's tutor flow works end to end on a phone viewport with no
 *     horizontal overflow (a layout wider than the screen is the first symptom
 *     of a desktop-only grid).
 */

test.describe.configure({ timeout: 5 * 60_000 });

const STUDENT = "student1@e2e.test";

test("mobile: bottom navigation targets are at least 44px and fit the viewport", async ({
  page,
}) => {
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT);
  await openRoute(page, "/student");

  const nav = page.getByRole("navigation", { name: /প্রধান নেভিগেশন|Main/ });
  await expect(nav).toBeVisible({ timeout: 30_000 });
  const links = nav.getByRole("link");
  const count = await links.count();
  expect(count, "the bottom nav exposes its destinations").toBeGreaterThan(2);

  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  for (let i = 0; i < count; i += 1) {
    const box = await links.nth(i).boundingBox();
    expect(box, `nav link ${i} has a layout box`).not.toBeNull();
    expect(box!.height, `nav link ${i} is at least 44px tall`).toBeGreaterThanOrEqual(44);
    expect(box!.x + box!.width - 1, `nav link ${i} stays inside the viewport`).toBeLessThanOrEqual(
      viewport!.width,
    );
  }

  // No horizontal overflow: the document may not be wider than the screen.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow, "no horizontal overflow on the mobile viewport").toBeLessThanOrEqual(1);
});

test("mobile: a student asks the tutor and gets an answer", async ({ page }) => {
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT);
  await openRoute(page, "/student/tutor");

  const composer = page.getByLabel(COMPOSER_LABEL);
  await expect(composer).toBeVisible({ timeout: 30_000 });
  await composer.fill("কোষ কী?");
  await composer.press("Enter");
  // The grounded answer arrives via SSE; the mock provider answers instantly.
  await expect(page.locator(".bubble.assistant").last()).toContainText(
    /কোষ|পাঠ্যবই/,
    { timeout: 60_000 },
  );

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow, "no horizontal overflow after an answer").toBeLessThanOrEqual(1);
});
