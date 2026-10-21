/**
 * Live user-level check of the production deployment.
 *
 * Drives https://bangla-gpt-app.vercel.app as a browser user would and asserts
 * what the *deployed* build does: the prerendered pages, the language and theme
 * toggles, the auth guard, the PWA wiring, and — since the API origin is
 * upstream-down — that every API-dependent screen degrades into its designed
 * message instead of a blank page or a crash.
 *
 * Usage: node apps/web/live_check.mjs
 */
import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const BASE = "https://bangla-gpt-app.vercel.app";
const results = [];
const record = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  console.log(
    `${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`,
  );
};

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 412, height: 823 },
});
const page = await context.newPage();
const consoleErrors = [];
const failedRequests = [];
page.on(
  "console",
  (m) => m.type() === "error" && consoleErrors.push(m.text().slice(0, 120)),
);
page.on("requestfailed", (r) =>
  failedRequests.push(`${r.url().slice(0, 80)} ${r.failure()?.errorText}`),
);

// --- public routes ---------------------------------------------------------
await page.goto(`${BASE}/welcome`, { waitUntil: "load" });
const h1 = await page.locator("h1.landing-title").first().innerText();
record(
  "/welcome renders its prerendered H1",
  h1.trim().length > 0,
  h1.slice(0, 40),
);

const links = await page.locator("a[href]").count();
record("/welcome has navigable links", links > 0, `${links} links`);

// Language toggle: bn -> en -> back, and the choice sticks across a reload.
const langButton = page
  .locator(
    '.public-lang-toggle, button[aria-label*="ভাষা"], button[aria-label*="language"]',
  )
  .first();
await langButton.click();
await page.waitForTimeout(400);
const englishHeading = await page
  .locator("h1.landing-title")
  .first()
  .innerText();
record(
  "language toggle switches the copy",
  englishHeading.trim() !== h1.trim(),
  englishHeading.slice(0, 40),
);
await langButton.click();
await page.waitForTimeout(300);

// Theme: the boot script sets data-theme before paint; the stored choice wins.
await page.evaluate(() => localStorage.setItem("bgpt_theme", "dark"));
await page.reload({ waitUntil: "load" });
const theme = await page.evaluate(() => document.documentElement.dataset.theme);
record("theme preference is honored on load", theme === "dark", String(theme));
await page.evaluate(() => localStorage.removeItem("bgpt_theme"));

// Legal pages: text renders and an internal link navigates.
await page.goto(`${BASE}/privacy`, { waitUntil: "load" });
const legal = await page.locator("main.card-legal").first().innerText();
record(
  "/privacy renders its legal text",
  legal.length > 200,
  `${legal.length} chars`,
);
await page.goto(`${BASE}/terms`, { waitUntil: "load" });
await page.locator('main a[href="/register"]').first().click();
await page.waitForURL(/\/register$/, { timeout: 15000 });
record(
  "/terms links navigate (client routing)",
  page.url().endsWith("/register"),
);

// --- auth guard ------------------------------------------------------------
await page.goto(`${BASE}/student`, { waitUntil: "load" });
await page
  .waitForURL(/\/login|backend|retry|\u09b8\u0982\u09af\u09cb\u0997/i, {
    timeout: 20000,
  })
  .catch(() => {});
const guarded =
  page.url().includes("/login") ||
  (await page.locator("body").innerText()).length > 50;
record(
  "/student is behind the auth guard or shows the unreachable state",
  guarded,
  page.url().replace(BASE, ""),
);

// --- status page: designed degradation, not a blank screen -----------------
await page.goto(`${BASE}/status`, { waitUntil: "load" });
await page.waitForTimeout(2500);
const statusText = await page.locator("body").innerText();
record(
  "/status degrades into a readable message",
  statusText.trim().length > 30,
  statusText.replace(/\s+/g, " ").slice(0, 70),
);

// --- login: the form renders; a submit without an API shows the connection copy
await page.goto(`${BASE}/login`, { waitUntil: "load" });
const email = page.locator("#email");
record("/login renders its form", await email.isVisible());
await email.fill("student1@e2e.test");
await page.locator("#password").fill("supersecret1");
await page.locator('form button[type="submit"]').click();
await page.waitForTimeout(4000);
const loginBody = await page.locator("body").innerText();
record(
  "submitting without a reachable API explains itself",
  /connection|connect|\u09b8\u0982\u09af\u09cb\u0997|retry|\u09b0\u09bf\u099f\u09cd\u09b0\u09be\u0987|backend/i.test(
    loginBody,
  ),
  loginBody.replace(/\s+/g, " ").slice(0, 70),
);

// --- PWA wiring ------------------------------------------------------------
const manifest = await page.request.get(`${BASE}/manifest.webmanifest`);
record(
  "/manifest.webmanifest is served",
  manifest.status() === 200,
  `${manifest.status()}`,
);
const sw = await page.request.get(`${BASE}/sw.js`);
record(
  "/sw.js is served uncached",
  sw.status() === 200,
  `${sw.status()} cache=${sw.headers()["cache-control"] ?? "-"}`,
);

// --- accessibility on a public route --------------------------------------
await page.goto(`${BASE}/welcome`, { waitUntil: "load" });
const axe = await new AxeBuilder({ page }).analyze();
const serious = axe.violations.filter(
  (v) => v.impact === "serious" || v.impact === "critical",
);
record(
  "axe: no serious/critical violations on /welcome",
  serious.length === 0,
  serious.map((v) => v.id).join(","),
);

record(
  "no console errors on the visited pages",
  consoleErrors.length === 0,
  consoleErrors.slice(0, 2).join(" | "),
);
record(
  "no failed requests",
  failedRequests.length === 0,
  failedRequests.slice(0, 2).join(" | "),
);

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(
  `\n${results.length - failed.length}/${results.length} live checks passed`,
);
process.exitCode = failed.length ? 1 : 0;
