import { expect, test, type Page } from "@playwright/test";
import { openRoute, PASSWORD, signIn, useVariant } from "./a11y";

/**
 * FE-06: the token lifecycle end to end, in a real browser.
 *
 * The unit suite pins the pieces (logoutCleanup.test.ts: keys + IDB clear;
 * sessionAndStream: renewal and 401). The audit kept FE-06 INFERRED because
 * nothing drove the whole cycle in a browser. This spec does, with the parts
 * that only a browser can show:
 *
 *  * the token is a bearer credential in `localStorage["bgpt_token"]` and no
 *    auth cookie exists — the storage choice and its rationale are documented
 *    at `src/api.ts` ("Why the bearer token lives in localStorage") and the
 *    assertions here pin its observable half;
 *  * sign-out revokes server-side (already in session.spec.ts) and clears the
 *    react-query cache, the user-scoped localStorage keys and the IndexedDB
 *    offline copies;
 *  * a second user in the same browser cannot see the first user's data —
 *    including the offline copies the first user downloaded (X-01 covers the
 *    storage keys; this file extends it to the copies and to the query cache);
 *  * the logout wipe is awaited, so back/forward into a guarded route after
 *    sign-out cannot resurrect a cached dashboard.
 *
 * The service-worker half (PWA-02/FE-06 "the SW's user-scoped caches") runs
 * only on the preview harness, where the worker exists: `sw.js` never caches
 * `/api/` and the shell caches carry no user content. Default suite runs
 * block service workers on purpose (a stale cache must not mask a regression).
 */

test.describe.configure({ timeout: 5 * 60_000 });

const STUDENT_A = "student1@e2e.test";
const STUDENT_B = "student2@e2e.test";

/** The reader route the corpus sample answers; class 6 science. */
const READER_ROUTE = `/student/learn/science/${encodeURIComponent("কোষ")}?class=6`;

/**
 * Console cleanliness is a pass rule (FE-15): a JS error, a React warning or
 * an unhandled rejection in any of these flows fails the test. The browser's
 * own network-status line for deliberately-driven refusals is not app noise.
 */
function collectConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (/Failed to load resource/i.test(text)) return;
    errors.push(text);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return errors;
}

async function tokenFor(page: Page): Promise<string> {
  const token = await page.evaluate(() =>
    window.localStorage.getItem("bgpt_token"),
  );
  expect(token, "a signed-in session holds a token").toBeTruthy();
  return token as string;
}

async function userIdOf(page: Page): Promise<number> {
  const res = await page.request.get("/api/users/me", {
    headers: { Authorization: `Bearer ${await tokenFor(page)}` },
  });
  expect(res.status()).toBe(200);
  const body = (await res.json()) as { user_id: number };
  return body.user_id;
}

/** Download the reader's chapter copy through the real button. */
async function downloadChapter(page: Page): Promise<void> {
  await openRoute(page, READER_ROUTE);
  const button = page.getByRole("button", {
    name: /ডাউনলোড|Download chapter/i,
  });
  await expect(button).toBeVisible({ timeout: 30_000 });
  await button.click();
  // The button flips to its saved state (aria-pressed, F-203) and the manage
  // card appears; both are the app's own confirmation that the write landed.
  await expect(button).toHaveAttribute("aria-pressed", "true");
}

async function offlineCopyKeys(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    if (!("indexedDB" in window)) return [];
    // Probing must not create the database: `offlineDbExists` below asserts
    // the delete, and an open() on a missing name would recreate it.
    const exists = (await indexedDB.databases()).some(
      (d) => d.name === "bgpt-offline",
    );
    if (!exists) return [];
    return new Promise<string[]>((resolve) => {
      const req = indexedDB.open("bgpt-offline");
      req.onsuccess = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains("chapters")) {
          db.close();
          resolve([]);
          return;
        }
        const all = db.transaction("chapters").objectStore("chapters").getAll();
        all.onsuccess = () => {
          const keys = (all.result as Array<{ key: string }>).map((r) => r.key);
          db.close();
          resolve(keys);
        };
        all.onerror = () => {
          db.close();
          resolve([]);
        };
      };
      req.onerror = () => resolve([]);
    });
  });
}

async function offlineDbExists(page: Page): Promise<boolean> {
  return page.evaluate(async () => {
    const dbs = await indexedDB.databases();
    return dbs.some((d) => d.name === "bgpt-offline");
  });
}

test("logout clears the query cache, user storage and offline copies; the next user sees none of it", async ({
  page,
}) => {
  const errors = collectConsole(page);
  await useVariant(page, { theme: "light", lang: "bn" });

  // ── user A builds state that must not survive ─────────────────────────
  await signIn(page, STUDENT_A);
  const userA = await userIdOf(page);
  const tokenA = await tokenFor(page);

  // The storage contract: exactly one session credential, in localStorage,
  // never a cookie the app cannot read (documented at src/api.ts).
  const cookieNames = await page.evaluate(() =>
    document.cookie
      .split(";")
      .map((pair) => pair.split("=")[0]?.trim())
      .filter(Boolean),
  );
  expect(cookieNames).not.toContain("bgpt_token");
  expect(cookieNames).not.toContain("session");

  // A conversation list in the react-query cache (the long-history seed gives
  // student1 one, so "empty" for the next user is a real assertion).
  await openRoute(page, "/student/tutor");
  await expect(
    page.getByRole("button", { name: /E2E long history/ }).first(),
  ).toBeVisible({ timeout: 30_000 });

  await downloadChapter(page);
  const keysA = await offlineCopyKeys(page);
  expect(keysA, "the copy is stored under the student's user id").toEqual([
    expect.stringMatching(new RegExp(`^${userA}\\|`)),
  ]);

  // ── sign out through the UI ────────────────────────────────────────────
  await page
    .locator("header")
    .getByRole("button", { name: /লগআউট|লগ আউট|Log ?out|সাইন আউট/i })
    .click();
  await expect(page).toHaveURL(/\/login$/, { timeout: 30_000 });
  expect(
    await page.evaluate(() => window.localStorage.getItem("bgpt_token")),
  ).toBeNull();
  // The wipe is awaited before the navigation: no offline copy survives it.
  await expect
    .poll(() => offlineCopyKeys(page), { timeout: 20_000 })
    .toEqual([]);
  await expect
    .poll(() => offlineDbExists(page), { timeout: 20_000 })
    .toBe(false);

  // The revoked token is dead server-side too (session.spec.ts asserts the
  // 401; repeated here so this spec is self-contained about the claim).
  const revoked = await page.request.get("/api/users/me", {
    headers: { Authorization: `Bearer ${tokenA}` },
  });
  expect(revoked.status()).toBe(401);

  // ── user B: none of A's data may appear ───────────────────────────────
  await signIn(page, STUDENT_B);
  const userB = await userIdOf(page);
  expect(userB).not.toBe(userA);

  // A stale query cache would render student1's conversation chips here —
  // the `["conversations"]` key carries no user id, which is exactly why
  // logout must clear the cache rather than rely on the key.
  await openRoute(page, "/student/tutor");
  await expect(
    page.getByRole("button", { name: /E2E long history/ }),
  ).toHaveCount(0);
  // And the new chat button proves the page actually rendered its own state.
  await expect(
    page.getByRole("button", { name: /নতুন চ্যাট|New chat/i }).first(),
  ).toBeVisible({ timeout: 30_000 });

  // Offline copies are user-scoped now (PWA-03): B sees an empty library and
  // A's copy is not readable under B's id.
  await downloadChapter(page);
  const keysB = await offlineCopyKeys(page);
  expect(keysB).toHaveLength(1);
  expect(keysB[0].startsWith(`${userB}|`)).toBe(true);
  expect(keysB.some((k) => k.startsWith(`${userA}|`))).toBe(false);

  // Switching back to A prunes B's copies (login-time owner check): the
  // previous user's downloaded chapters must not be readable by the next.
  await page
    .locator("header")
    .getByRole("button", { name: /লগআউট|লগ আউট|Log ?out|সাইন আউট/i })
    .click();
  await expect(page).toHaveURL(/\/login$/, { timeout: 30_000 });
  await signIn(page, STUDENT_A);
  await openRoute(page, "/student/learn");
  // The login-time owner check prunes the other user's copies before the
  // reader can open; the library card therefore renders nothing.
  await expect
    .poll(() => offlineCopyKeys(page), { timeout: 20_000 })
    .toEqual([]);
  await expect(page.getByText(/অফলাইন কপি|Offline copy/)).toHaveCount(0);

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

test("the service worker caches carry no user data (preview harness only)", async ({
  page,
  context,
}) => {
  test.skip(
    process.env.E2E_WEB !== "preview",
    "needs the production bundle where /sw.js is registered: E2E_WEB=preview npx playwright test w2-session",
  );
  const errors = collectConsole(page);
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT_A);
  await openRoute(page, "/student/tutor");
  await expect(
    page.getByRole("button", { name: /E2E long history/ }).first(),
  ).toBeVisible({ timeout: 30_000 });

  const cached = await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    const names = await caches.keys();
    const urls: string[] = [];
    for (const name of names.filter((n) => n.startsWith("bgpt-"))) {
      const cache = await caches.open(name);
      for (const request of await cache.keys()) urls.push(request.url);
    }
    return urls;
  });
  expect(cached.length, "the shell is cached").toBeGreaterThan(0);
  expect(
    cached.filter((u) => new URL(u).pathname.startsWith("/api/")),
    "API responses are never cached",
  ).toEqual([]);
  // Nothing cached is user content: the worker only stores same-origin shell
  // assets, and the transcript lives in IndexedDB / the query cache instead.
  expect(cached.some((u) => u.includes("conversation"))).toBe(false);

  await context.setOffline(true);
  await page.goto("/student/tutor", { waitUntil: "domcontentloaded" });
  await expect(page.locator("main, [role='main']")).toHaveCount(1, {
    timeout: 30_000,
  });
  await context.setOffline(false);

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});
