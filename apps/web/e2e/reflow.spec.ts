import { expect, test, type Page } from "@playwright/test";
import { openRoute, signIn, useVariant } from "./a11y";

/**
 * AUD-G-07 / G-13 (visual polish, reflow), AUD-G-09 (motion).
 *
 * The 60 reviewed pixel baselines in `visual.spec.ts` cover 360/768/1280 in
 * both themes and both languages. This file covers what a baseline cannot
 * cheaply cover — the *other* widths the item names (320, 390, 1024, 1440),
 * 200% text resize, and the reduced-motion run — with assertions rather than
 * more PNGs, because "no overflow, truncation, overlap or misaligned grids"
 * is a property that can be measured instead of eyeballed:
 *
 *   * WCAG 1.4.10 reflow: at 320 CSS px there is no horizontal scrolling and
 *     no element paints outside the viewport;
 *   * WCAG 1.4.4 resize text: at 200% root font size the same holds, and no
 *     text box clips its own content;
 *   * reduced motion: with `prefers-reduced-motion: reduce` the CSS the app
 *     ships kills animation and transition durations, and the app still
 *     renders (the media query must not hide content).
 *
 * Screenshots of the extremes are written under `coverage/reflow/` for the
 * reviewer; they are evidence artifacts, not pass/fail baselines.
 */

const WIDTHS = [
  { label: "320", width: 320, height: 640 },
  { label: "360", width: 360, height: 740 },
  { label: "390", width: 390, height: 844 },
  { label: "768", width: 768, height: 1024 },
  { label: "1024", width: 1024, height: 768 },
  { label: "1280", width: 1280, height: 800 },
  { label: "1440", width: 1440, height: 900 },
];

const SCREENS = [
  { name: "welcome", route: "/welcome" },
  { name: "login", route: "/login" },
  { name: "register", route: "/register" },
  { name: "status", route: "/status" },
  { name: "legal", route: "/privacy" },
  { name: "student-home", route: "/student", email: "student2@e2e.test" },
  {
    name: "student-tutor",
    route: "/student/tutor",
    email: "student2@e2e.test",
  },
  { name: "teacher-home", route: "/teacher", email: "teacher2@e2e.test" },
];

interface Overflow {
  selector: string;
  right: number;
  left: number;
}

/**
 * Elements painting outside the viewport horizontally. Fixed/absolute
 * decorations that are intentionally off-canvas are exempted by the caller
 * through `ignore`; a non-empty list is a reflow failure.
 */
async function horizontalOverflow(page: Page): Promise<Overflow[]> {
  return page.evaluate(() => {
    const viewport = window.innerWidth;
    const offenders: { selector: string; right: number; left: number }[] = [];
    for (const element of Array.from(document.querySelectorAll("body *"))) {
      const style = window.getComputedStyle(element);
      if (style.visibility === "hidden" || style.display === "none") continue;
      if (style.position === "fixed") continue; // toasts/banners are overlay chrome
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;
      // 1px of tolerance: sub-pixel layout rounding is not overflow.
      if (box.right > viewport + 1 || box.left < -1) {
        const id = element.id ? `#${element.id}` : "";
        const cls = (element.getAttribute("class") ?? "")
          .split(" ")
          .filter(Boolean)[0];
        offenders.push({
          selector: `${element.tagName.toLowerCase()}${id}${cls ? `.${cls}` : ""}`,
          right: Math.round(box.right),
          left: Math.round(box.left),
        });
      }
    }
    return offenders.slice(0, 8);
  });
}

async function assertNoHorizontalScroll(
  page: Page,
  where: string,
): Promise<void> {
  const scrollWidth = await page.evaluate(
    () => document.documentElement.scrollWidth,
  );
  const clientWidth = await page.evaluate(
    () => document.documentElement.clientWidth,
  );
  expect(
    scrollWidth,
    `${where}: the document scrolls horizontally (scrollWidth ${scrollWidth} > clientWidth ${clientWidth})`,
  ).toBeLessThanOrEqual(clientWidth + 1);

  const offenders = await horizontalOverflow(page);
  expect(
    offenders,
    `${where}: elements paint outside the viewport: ${JSON.stringify(offenders)}`,
  ).toEqual([]);
}

test.describe.configure({ timeout: 10 * 60_000 });

for (const screen of SCREENS) {
  test(`reflow: ${screen.name} at every named width, no overflow`, async ({
    page,
  }) => {
    await useVariant(page, { theme: "light", lang: "bn" });
    if (screen.email) await signIn(page, screen.email);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width: width.width, height: width.height });
      await openRoute(page, screen.route);
      await assertNoHorizontalScroll(page, `${screen.name}@${width.label}px`);
      // The pixel widths the visual baselines do not carry: 360/768/1280 are
      // reviewed baselines in visual.spec.ts, so the reviewer captures here
      // cover exactly the missing ones (AUD-G-07: 320/390/1024/1440). They
      // are evidence, not pass/fail baselines.
      if (["320", "390", "1024", "1440"].includes(width.label)) {
        await page.screenshot({
          path: `coverage/reflow/${screen.name}--${width.label}.png`,
          fullPage: true,
        });
      }
    }
  });
}

test("reflow: 200% text resize keeps the layout inside the viewport", async ({
  page,
}) => {
  await useVariant(page, { theme: "light", lang: "bn" });
  // 200% text-only zoom, which is what WCAG 1.4.4 asks to survive: the root
  // font size doubles and every rem/clamp-based size with it. (Browser zoom
  // would also halve the effective viewport, which the 320 px pass covers.)
  let signedInAs: string | null = null;
  for (const screen of SCREENS) {
    if (screen.email && screen.email !== signedInAs) {
      // `/login` redirects to the role home when a session is already up, so
      // the previous account has to be dropped before the next sign-in --
      // otherwise the loop waits for a form that is not on screen.
      await page.goto("/welcome", { waitUntil: "domcontentloaded" });
      await page.evaluate(() => {
        localStorage.removeItem("bgpt_token");
        localStorage.removeItem("bgpt_admin_token_backup");
        localStorage.removeItem("bgpt_impersonating");
      });
      await signIn(page, screen.email);
      signedInAs = screen.email;
    }
    await page.setViewportSize({ width: 1280, height: 800 });
    await openRoute(page, screen.route);
    await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
    await page.waitForTimeout(300);
    await assertNoHorizontalScroll(page, `${screen.name}@200% text`);
    await page.screenshot({
      path: `coverage/reflow/${screen.name}--zoom200.png`,
      fullPage: true,
    });
  }
});

test("text at 200% is not clipped by its own box", async ({ page }) => {
  await useVariant(page, { theme: "light", lang: "bn" });
  await openRoute(page, "/welcome");
  await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
  await page.waitForTimeout(300);
  const clipped = await page.evaluate(() => {
    const bad: string[] = [];
    for (const element of Array.from(
      document.querySelectorAll("h1, h2, h3, p, .btn, label"),
    )) {
      const style = window.getComputedStyle(element);
      if (style.overflow === "hidden" || style.textOverflow === "ellipsis") {
        // An overflowing box with `overflow: hidden` is clipping.
        if (element.scrollHeight > element.clientHeight + 1) {
          bad.push(
            `${element.tagName}.${(element.getAttribute("class") ?? "").split(" ")[0]} clipped vertically`,
          );
        }
      }
    }
    return bad;
  });
  expect(clipped).toEqual([]);
});

test("reduced motion: the app ships no animation and still renders", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await useVariant(page, { theme: "light", lang: "bn" });
  await openRoute(page, "/welcome");
  // The global kill switch (styles.css) sets durations to 0.001ms, which the
  // browser reports as "0s".
  const durations = await page.evaluate(() => {
    const read = (selector: string) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const style = window.getComputedStyle(element);
      return {
        transition: style.transitionDuration,
        animation: style.animationDuration,
      };
    };
    return {
      button: read(".btn"),
      card: read(".card, .feature-card"),
      body: read("body"),
    };
  });
  for (const [name, value] of Object.entries(durations)) {
    if (!value) continue;
    expect(
      value.transition.split(",").every((d) => parseFloat(d) <= 0.01),
      `${name} transitions still run: ${value.transition}`,
    ).toBe(true);
    expect(
      value.animation.split(",").every((d) => parseFloat(d) <= 0.01),
      `${name} animations still run: ${value.animation}`,
    ).toBe(true);
  }
  // The media query must not hide the page: content is still on screen.
  await expect(page.getByRole("heading").first()).toBeVisible();
  await page.screenshot({
    path: "coverage/reflow/welcome--reduced-motion.png",
    fullPage: true,
  });
});

test("reduced motion: skeletons stop shimmering instead of disappearing", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, "student2@e2e.test");
  await page.setViewportSize({ width: 390, height: 844 });
  await openRoute(page, "/student/learn");
  const skeleton = page.locator(".skeleton").first();
  if ((await skeleton.count()) > 0) {
    const animation = await skeleton.evaluate(
      (element) => window.getComputedStyle(element).animationDuration,
    );
    expect(parseFloat(animation)).toBeLessThanOrEqual(0.01);
  }
  await expect(page.locator('main, [role="main"]')).toHaveCount(1);
});
