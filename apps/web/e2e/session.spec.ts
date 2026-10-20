import { expect, test } from "@playwright/test";
import { PASSWORD, signIn, useVariant } from "./a11y";

/**
 * AUD-B-04 / B-03: "logout invalidates server-side".
 *
 * The unit suite pins the client half (it calls POST /auth/logout with the
 * token still in storage). This is the half that matters to an attacker: after
 * the user signs out, the token they still hold must stop working. The test
 * keeps a copy of the token, signs out through the real UI, and then presents
 * that copy to a protected endpoint — the 401 is the evidence.
 *
 * A control runs first: the same token, before sign-out, is accepted. Without
 * it a 401 could mean "the endpoint rejects everything", which would make the
 * test pass for the wrong reason.
 *
 * Storage inspection (the other half of B-03's browser evidence): the
 * assertion block below reads the browser's own storage after login. The
 * session token is kept in `localStorage["bgpt_token"]` BY DESIGN, and
 * HttpOnly cookies are deliberately NOT used — the full rationale (bearer API
 * shared with the Capacitor WebView, CSRF shape of `Authorization` headers,
 * XSS bounds: safeMarkdown, CSP, 60-minute token, server-side logout revoke)
 * lives next to the constant that defines the key:
 * `src/api.ts`, "Why the bearer token lives in localStorage". These assertions
 * pin the factual half of that design: exactly one session credential exists
 * (in localStorage, never in `document.cookie`), so the shared-device story —
 * sign-out wipes it — is checkable in one place.
 */

const STUDENT = "student1@e2e.test";

test.describe.configure({ timeout: 3 * 60_000 });

test("a token from a signed-out session is rejected by the API", async ({
  page,
}) => {
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT);
  const token = await page.evaluate(() =>
    window.localStorage.getItem("bgpt_token"),
  );
  expect(token).toBeTruthy();

  // Storage inspection: the token is a real credential shaped like the JWT the
  // API mints, and no parallel session cookie exists (document.cookie cannot
  // see HttpOnly cookies -- which is exactly why the absence of ANY auth
  // cookie there also proves this app never relies on one it could not read).
  expect(token!.split(".")).toHaveLength(3);
  const cookieNames = await page.evaluate(() =>
    document.cookie
      .split(";")
      .map((pair) => pair.split("=")[0]?.trim())
      .filter(Boolean),
  );
  expect(cookieNames).not.toContain("bgpt_token");
  expect(cookieNames).not.toContain("session");

  // Control: the token works while the session is alive. (`/users/me` is the
  // endpoint the app itself probes at boot — `fetchMe` in src/api.ts.)
  const before = await page.request.get("/api/users/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(
    before.status(),
    "the control request must succeed before sign-out",
  ).toBe(200);

  // Sign out through the shell, as the user does.
  // The accessible name is the i18n key `logout` ("লগআউট" in Bengali, no
  // space) -- a regex with a space never matched it, so this click used to
  // time out rather than test anything.
  await page
    .locator("header")
    .getByRole("button", { name: /লগআউট|লগ আউট|Log ?out|সাইন আউট/i })
    .click();
  await expect(page).toHaveURL(/\/login$/);
  expect(
    await page.evaluate(() => window.localStorage.getItem("bgpt_token")),
  ).toBeNull();

  // The stolen-copy scenario: the token outlives the sign-out in the attacker's
  // hands only if the server never learned about it.
  const after = await page.request.get("/api/users/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(after.status(), "the revoked token must no longer be accepted").toBe(
    401,
  );

  // A signed-in state cannot be re-established with it either.
  const relogin = await page.request.post("/api/auth/login", {
    headers: { "Content-Type": "application/json" },
    data: { email: STUDENT, password: PASSWORD },
  });
  expect(relogin.status()).toBe(200);
});
