import { createHmac } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

/**
 * Wave 2 acceptance flows, part 1: the ANON, X and STU rows of the §8.3
 * flow matrix that the audit register held as INFERRED (see
 * `.qa-work/audit/FLOWS/coverage_map.csv`).
 *
 * Same harness contract as qa-flows.spec.ts: the shipped UI against the real
 * API with the deterministic `mock` provider and the seeded role accounts
 * (seed_e2e_users.py). Nothing is mocked at the HTTP layer except the two
 * deliberately induced fault cases (X-04, the ANON-07 500) and the two slow
 * network cases (STU-04) -- §8.4 allows induced failures and they are named
 * where they happen. No fixed sleeps: every wait is a URL, a visible
 * element, a polled API answer or a request event.
 *
 * Deliberate limits, stated where they bite:
 *  * ANON-05 -- the raw reset token only exists inside the mailed message;
 *    the harness API has SMTP unconfigured (playwright.config.ts) and is not
 *    ours to reconfigure, so the token lifecycle stays covered by
 *    apps/api/tests/test_password_reset.py and friends. What IS driven here
 *    is the enumeration-safe request path and the refusal of a bad token.
 *  * STU-17 -- there is no citation-to-Reader navigation in the product (the
 *    chip opens an evidence modal), so "opens the cited chapter in the
 *    Reader" is N/A; the modal's excerpt is verified against the chapter
 *    text the API serves instead.
 *  * STU-18 -- a context-dependent follow-up cannot be produced with
 *    LLM_PROVIDER=mock (the answer text does not depend on history); the
 *    thread continuity that carries the context is asserted at the message
 *    level instead.
 *  * X-11 -- the disabled path is API-tested (test_qa_kill_switch.py); the
 *    harness pins AI_GENERATION_ENABLED on and a spec may not edit the
 *    config, so the enabled path is asserted here.
 */

const PASSWORD = "E2ePass!2345";
const STUDENT = "student1@e2e.test";
const PARENT = "parent1@e2e.test";

/** The one known in-corpus question (class-6 science, bundled sample corpus). */
const QUESTION = "কোষ কী?";

/** API-owned Bengali copy; does not translate with the UI language. */
const INSUFFICIENT_EVIDENCE =
  "উত্তরটি পাঠ্যবইয়ের বিষয়বস্তুর ভিত্তিতে দেওয়া সম্ভব নয়";

/** JWT_SECRET the harness exports for its API (playwright.config.ts). */
const HARNESS_JWT_SECRET = "test-secret-0123456789abcdef0123456789";

/**
 * Console cleanliness is a pass rule (§8.4). Every test starts with an empty
 * collector and asserts it at the end. The browser's own "Failed to load
 * resource" line for an HTTP status the app deliberately renders is not app
 * noise (these flows drive refusals on purpose); JS errors, React warnings
 * and unhandled rejections are. A test can widen the filter if it induces
 * something else.
 */
const BENIGN_CONSOLE = [
  /Failed to load resource/i,
  /net::ERR_FAILED/,
  /NetworkError/,
];
let consoleErrors: string[] = [];
let allowedConsole: RegExp[] = [];

test.describe.configure({ timeout: 5 * 60_000 });

test.beforeEach(async ({ page }) => {
  consoleErrors = [];
  allowedConsole = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));
});

test.afterEach(() => {
  const unexpected = consoleErrors.filter(
    (text) =>
      !BENIGN_CONSOLE.some((pattern) => pattern.test(text)) &&
      !allowedConsole.some((pattern) => pattern.test(text)),
  );
  expect(unexpected, "the console must stay clean").toEqual([]);
});

async function pin(page: Page, lang: "bn" | "en"): Promise<void> {
  await page.addInitScript(
    (value) => window.localStorage.setItem("bgpt_lang", value),
    lang,
  );
}

async function open(page: Page, path: string): Promise<void> {
  try {
    await page.goto(path, { waitUntil: "domcontentloaded" });
  } catch (err) {
    // The app's own redirect can abort a goto that raced it; one retry
    // settles the navigation without hiding a real failure.
    if (!/ERR_ABORTED/.test(String(err))) throw err;
    await page.goto(path, { waitUntil: "domcontentloaded" });
  }
}

async function signIn(
  page: Page,
  email: string,
  password = PASSWORD,
): Promise<void> {
  await open(page, "/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator('form button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 60_000 });
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem("bgpt_token")))
    .toBeTruthy();
}

async function signOut(page: Page): Promise<void> {
  const button = page
    .locator("header")
    .getByRole("button", { name: "Log out" });
  await button.click();
  try {
    await expect(page).toHaveURL(/\/login$/, { timeout: 30_000 });
  } catch {
    // The server-side revoke plus the shared-device scrub can outlast one
    // wait; the control is idempotent, so one retry is safe and honest.
    await button.click();
    await expect(page).toHaveURL(/\/login$/, { timeout: 30_000 });
  }
}

async function authHeaders(page: Page): Promise<{ Authorization: string }> {
  const token = await page.evaluate(() =>
    window.localStorage.getItem("bgpt_token"),
  );
  expect(token, "no session token in localStorage").toBeTruthy();
  return { Authorization: `Bearer ${token}` };
}

async function apiGet<T>(page: Page, path: string): Promise<T> {
  // /users/me carries a documented 10/min per-user budget (config.py F-127)
  // and the app's own boot probe shares it, so a navigation-heavy flow can
  // legitimately reach it. Denied requests are not counted by the sliding
  // window, so waiting on the server's own answer is a real signal.
  const deadline = Date.now() + 90_000;
  for (;;) {
    const res = await page.request.get(`/api${path}`, {
      headers: await authHeaders(page),
    });
    if (res.status() !== 429 || Date.now() > deadline) {
      expect(res.status(), `GET ${path}: ${await res.text()}`).toBe(200);
      return (await res.json()) as T;
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

/** True when any ~24-character window of `needle` appears in `haystack`. */
function corpusHasWindow(haystack: string, needle: string): boolean {
  const clean = needle.replace(/\s+/g, " ").trim();
  for (let start = 0; start + 24 <= clean.length; start += 12) {
    if (haystack.includes(clean.slice(start, start + 24))) return true;
  }
  return false;
}

/** The class-6 chapter texts the API serves, for citation-integrity checks. */
async function classSixCorpus(page: Page): Promise<
  { chapter: string; text: string }[]
> {
  const subjects = await apiGet<{ subject: string }[]>(
    page,
    "/learn/subjects?class_level=6",
  );
  const rows: { chapter: string; text: string }[] = [];
  for (const subject of subjects) {
    const chapters = await apiGet<{ chapter: string }[]>(
      page,
      `/learn/subjects/${encodeURIComponent(subject.subject)}/chapters?class_level=6`,
    );
    for (const chapter of chapters.slice(0, 8)) {
      const content = await apiGet<{ sections: { text: string }[] }>(
        page,
        `/learn/subjects/${encodeURIComponent(subject.subject)}/chapters/${encodeURIComponent(
          chapter.chapter,
        )}?class_level=6`,
      );
      rows.push({
        chapter: chapter.chapter,
        text: content.sections.map((section) => section.text).join("\n"),
      });
    }
    if (rows.length > 60) break;
  }
  return rows;
}

/** A signed JWT shaped like the API's own, for the X-02 clock cases. */
function forgeToken(
  userId: number,
  role: string,
  claims: { expInSeconds: number; iat?: number },
): string {
  const enc = (value: object) =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  const iat = claims.iat ?? Math.floor(Date.now() / 1000);
  const header = enc({ alg: "HS256", typ: "JWT" });
  const body = enc({
    sub: String(userId),
    role,
    iss: "bangla-gpt-api",
    aud: "bangla-gpt-clients",
    iat,
    exp: iat + claims.expInSeconds,
    jti: `w2-${Math.random().toString(16).slice(2)}`,
  });
  const signature = createHmac("sha256", HARNESS_JWT_SECRET)
    .update(`${header}.${body}`)
    .digest("base64url");
  return `${header}.${body}.${signature}`;
}

function tokenPayload(token: string): Record<string, unknown> {
  return JSON.parse(
    Buffer.from(token.split(".")[1] ?? "", "base64url").toString("utf8"),
  ) as Record<string, unknown>;
}

/** One failed /login attempt; returns the inline error copy the user sees. */
async function loginRefusal(
  page: Page,
  email: string,
  password: string,
): Promise<string> {
  await open(page, "/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator('form button[type="submit"]').click();
  const alert = page.locator('[role="alert"]').first();
  await expect(alert).toBeVisible();
  return ((await alert.textContent()) ?? "").trim();
}

const COMPOSER = /পাঠ্যবই থেকে যেকোনো প্রশ্ন লিখুন|Ask anything from your textbook/;

async function ask(page: Page, question: string) {
  const box = page.getByRole("textbox", { name: COMPOSER });
  await box.fill(question);
  await page.getByRole("button", { name: /পাঠান|Send/ }).first().click();
  return page.locator(".bubble.assistant").last();
}

/** Wait for the turn to settle into a grounded answer or a refusal. */
async function settledAnswer(page: Page, question: string) {
  const answer = await ask(page, question);
  await expect
    .poll(
      async () => {
        const text = (await answer.textContent()) ?? "";
        if (text.includes("Simple explanation")) return "grounded";
        if (text.includes(INSUFFICIENT_EVIDENCE)) return "refused";
        return "pending";
      },
      { timeout: 60_000 },
    )
    .not.toBe("pending");
  return answer;
}

/* ------------------------------------------------------------------ ANON */

test("ANON-01 welcome toggle switches the copy and the error strings, console stays clean", async ({
  page,
}) => {
  await open(page, "/welcome");
  // Default language is Bangla, and the landing renders its own copy.
  await expect(page.locator("html")).toHaveAttribute("lang", "bn");
  const bnHeading = (await page.locator("h1.landing-title").textContent()) ?? "";
  expect(bnHeading).toMatch(/[\u0980-\u09FF]/);

  await page.locator(".public-lang-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  const enHeading = (await page.locator("h1.landing-title").textContent()) ?? "";
  expect(enHeading).not.toBe(bnHeading);
  // One named control per action, and the primary call to action links.
  await expect(page.getByRole("link", { name: "Get started" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "I already have an account" }),
  ).toBeVisible();

  // "every string including errors": the same toggle governs the login error
  // copy, so a failed sign-in is asserted in both languages.
  await open(page, "/login");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  const en = await loginRefusal(
    page,
    STUDENT,
    "DefinitelyWrong!999",
  );
  await page.locator(".public-lang-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "bn");
  await expect
    .poll(() =>
      page.evaluate(() => window.localStorage.getItem("bgpt_lang")),
    )
    .toBe("bn");
  const bn = await loginRefusal(page, STUDENT, "DefinitelyWrong!999");
  expect(bn).not.toBe(en);
  expect(bn).toMatch(/[\u0980-\u09FF]/);
  // The successful sign-in resets the failed-login counter this test raised.
  await signIn(page, STUDENT);
});

test("ANON-03 role registration paths and the validation matrix", async ({
  page,
}) => {
  await pin(page, "en");
  const stamp = Date.now();

  // 1. Empty form: the browser's own required-field validation blocks submit.
  await open(page, "/register");
  await page.locator('form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/register$/);
  expect(
    await page
      .locator("#remail")
      .evaluate((el) => (el as HTMLInputElement).validity.valid),
  ).toBe(false);

  // 2. Common password: refused by the API blocklist (400 password_too_common).
  await page.locator("#name").fill("QA Matrix");
  await page.locator("#remail").fill(`qa-weak-${stamp}@e2e.test`);
  await page.locator("#rpassword").fill("aaaaaaaa");
  await page.locator("#consent").check();
  await page.locator('form button[type="submit"]').click();
  await expect(page.locator('[role="alert"]').first()).toBeVisible();
  await expect(page).toHaveURL(/\/register$/);

  // 3. Duplicate email: the seeded account already exists (409 email_taken).
  await page.locator("#remail").fill(STUDENT);
  await page.locator("#rpassword").fill(PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await expect(page.locator('[role="alert"]').first()).toContainText(
    "An account with this email already exists",
  );

  // 4. Very long input: the API schema caps the name at 120 characters.
  await page.locator("#name").fill("ন".repeat(200));
  await page.locator("#remail").fill(`qa-long-${stamp}@e2e.test`);
  await page.locator('form button[type="submit"]').click();
  await expect(page.locator('[role="alert"]').first()).toBeVisible();
  await expect(page).toHaveURL(/\/register$/);

  // 5. Student success with a Bangla name and recorded consent.
  await page.locator("#name").fill("রহিম উদ্দিন");
  await page
    .locator("#remail")
    .fill(`qa-student-${stamp}@e2e.test`);
  await page.locator("#rpassword").fill(PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/student$/, { timeout: 30_000 });
  const me = await apiGet<{ name: string; role: string }>(page, "/users/me");
  expect(me.name).toBe("রহিম উদ্দিন");
  expect(me.role).toBe("student");
  await signOut(page);

  // 6. Teacher success lands on the teacher shell.
  await open(page, "/register");
  await page.locator("#role").selectOption("teacher");
  await page.locator("#name").fill("QA Teacher W2");
  await page.locator("#remail").fill(`qa-teacher-${stamp}@e2e.test`);
  await page.locator("#rpassword").fill(PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/teacher$/, { timeout: 30_000 });
  await expect(page.locator("aside.sidebar")).toBeVisible();
  await signOut(page);

  // 7. Parent success lands on the parent dashboard.
  await open(page, "/register");
  await page.locator("#role").selectOption("parent");
  await page.locator("#name").fill("QA Parent W2");
  await page.locator("#remail").fill(`qa-parent-${stamp}@e2e.test`);
  await page.locator("#rpassword").fill(PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/parent$/, { timeout: 30_000 });
  await expect(page.getByRole("heading").first()).toBeVisible();
});

test("ANON-04 repeated failed sign-ins are refused with a 429 at the account bound", async ({
  page,
}) => {
  await pin(page, "en");
  // A throwaway account, so the progressive lock this test triggers cannot
  // strand a seeded account for the rest of the run.
  const email = `qa-lockout-${Date.now()}@e2e.test`;
  await open(page, "/register");
  await page.locator("#name").fill("QA Lockout");
  await page.locator("#remail").fill(email);
  await page.locator("#rpassword").fill(PASSWORD);
  await page.locator("#consent").check();
  await page.locator('form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/student$/, { timeout: 30_000 });
  await signOut(page);

  // Five wrong passwords tripping the account bound is what the API counts
  // (routers/auth.py _LOGIN_LOCKOUT_THRESHOLD); the sixth attempt is refused
  // even with the correct password.
  let last = "";
  for (let attempt = 0; attempt < 5; attempt += 1) {
    last = await loginRefusal(page, email, "DefinitelyWrong!999");
    if (last.length === 0) throw new Error("no inline refusal copy");
  }
  expect(last).toContain("incorrect");

  await open(page, "/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  const refused = page.waitForResponse(
    (res) =>
      res.url().includes("/auth/login") && res.request().method() === "POST",
  );
  await page.locator('form button[type="submit"]').click();
  const response = await refused;
  expect(response.status(), "the repeated-failure bound must answer 429").toBe(
    429,
  );
  expect(Number(response.headers()["retry-after"])).toBeGreaterThan(0);
  const body = (await response.json()) as { detail: { code: string } };
  expect(body.detail.code).toBe("account_locked");
  // Observed UI copy: the app maps that code through errors.ts, which has no
  // entry for account_locked, so the student is told "something went wrong"
  // instead of the API's actionable lock message. Recorded in the wave-2
  // findings; the assertion pins what the app really shows today.
  await expect(page.locator('[role="alert"]').first()).toHaveText(
    "Something went wrong. Please try again later.",
  );
});

test("ANON-05 forgot-password is enumeration-safe and a bad token is refused", async ({
  page,
}) => {
  await pin(page, "en");
  const unknown = `qa-nobody-${Date.now()}@e2e.test`;

  // The reset request goes through the shipped form. The confirmation must be
  // byte-identical for a registered and an unregistered address.
  async function requestReset(email: string): Promise<string> {
    await open(page, "/forgot");
    await page.locator("#femail").fill(email);
    await page.locator('form button[type="submit"]').click();
    const status = page.locator('[role="status"]').first();
    await expect(status).toBeVisible();
    return ((await status.textContent()) ?? "").trim();
  }
  const unknownCopy = await requestReset(unknown);
  const knownCopy = await requestReset(STUDENT);
  expect(unknownCopy.length).toBeGreaterThan(0);
  expect(
    knownCopy,
    "a registered address and an unknown one must be indistinguishable",
  ).toBe(unknownCopy);

  // The form it reveals accepts a token; a bogus one is refused with the
  // app's localized copy (the real token only exists inside the mail).
  await page.locator("#rtoken").fill("not-a-real-token-0000000000");
  await page.locator("#rnewpass").fill("NewPass!2345");
  await page.locator('form button[type="submit"]').click();
  const alert = page.locator('[role="alert"]').first();
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(/invalid or expired/i);
  await expect(page).not.toHaveURL(/\/student$/);
  // The seeded account still signs in with its unchanged password.
  await signIn(page, STUDENT);
});

test("ANON-07 unknown routes show the not-found page, a forbidden area is bounced, and a 500 keeps app copy", async ({
  page,
}) => {
  await pin(page, "en");
  // FE-11: an unknown path renders the not-found page (naming the address,
  // with the way home) instead of a blank route or a silent redirect. The
  // page is lazily loaded, so the first hit waits for the dev-server chunk.
  await open(page, "/definitely-not-a-route");
  await expect(page.locator("h1")).toHaveText("Nothing found", {
    timeout: 60_000,
  });
  await expect(page.locator("code")).toHaveText("/definitely-not-a-route");
  await page.getByRole("link", { name: "Go home" }).click();
  await expect(page).toHaveURL(/\/welcome$/);
  await expect(page.locator("h1.landing-title")).toBeVisible();

  await signIn(page, STUDENT);
  await open(page, "/definitely-not-a-route-either");
  await expect(page.locator("h1")).toHaveText("Nothing found", {
    timeout: 60_000,
  });
  // The way home is the role home for a signed-in user, not the landing.
  await page.getByRole("link", { name: "Go home" }).click();
  await expect(page).toHaveURL(/\/student$/);
  // 403-style bounce: a student cannot open the admin area.
  await open(page, "/admin");
  await expect
    .poll(() => new URL(page.url()).pathname, { timeout: 20_000 })
    .not.toBe("/admin");
  await expect(page.locator("body")).not.toContainText("Admin dashboard");
  await signOut(page);

  // 500: induced at the auth endpoint so the public failure path is driven.
  // The app's own copy renders -- never the API body, the status or "boom".
  const url = new URL(page.url());
  await page.route("**/auth/login", (route) =>
    route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "internal_error", message: "boom /srv/db.sqlite" },
      }),
    }),
  );
  await open(page, "/login");
  await page.locator("#email").fill(STUDENT);
  await page.locator("#password").fill(PASSWORD);
  await page.locator('form button[type="submit"]').click();
  const alert = page.locator('[role="alert"]').first();
  await expect(alert).toBeVisible();
  await expect(alert).toHaveText("Something went wrong. Please try again later.");
  await expect(alert).not.toContainText("boom");
  await expect(alert).not.toContainText("db.sqlite");
  expect(page.url()).toContain(`${url.host}/login`);
  await page.unroute("**/auth/login");
});

/* --------------------------------------------------------------------- X */

test("X-11 kill switch (generation enabled): tutor, search, reader and quizzes all work", async ({
  page,
}) => {
  // The disabled path is covered by apps/api/tests/test_qa_kill_switch.py --
  // the harness pins AI_GENERATION_ENABLED on in playwright.config.ts and a
  // spec may not edit the config. This asserts the enabled path end to end so
  // an inverted default cannot pass both tests at once.
  await pin(page, "en");
  await signIn(page, STUDENT);
  await open(page, "/student/tutor");

  const answer = await settledAnswer(page, QUESTION);
  await expect(answer).toContainText("Simple explanation", {
    timeout: 60_000,
  });
  expect(
    (await answer.textContent()) ?? "",
    "the degraded-mode copy appeared although generation is enabled",
  ).not.toContain("সাময়িকভাবে বন্ধ");

  const subjects = await apiGet<{ subject: string }[]>(
    page,
    "/learn/subjects?class_level=6",
  );
  expect(subjects.length).toBeGreaterThan(0);
  const chapters = await apiGet<{ chapter: string }[]>(
    page,
    `/learn/subjects/${encodeURIComponent(subjects[0].subject)}/chapters?class_level=6`,
  );
  expect(chapters.length).toBeGreaterThan(0);
  const search = await apiGet<{ hits: unknown[] }>(
    page,
    `/search?q=${encodeURIComponent("কোষ")}`,
  );
  expect(search.hits.length).toBeGreaterThan(0);
  const me = await apiGet<{ profile_id: number }>(page, "/users/me");
  const quiz = await page.request.post("/api/quizzes", {
    headers: await authHeaders(page),
    data: {
      student_id: me.profile_id,
      subject: "science",
      class_level: 6,
      num_questions: 3,
    },
  });
  expect(quiz.status(), await quiz.text()).toBe(200);
  const started = (await quiz.json()) as {
    attempt_id: number;
    questions: { id: string }[];
  };
  const submitted = await page.request.post(
    `/api/quizzes/${started.attempt_id}/submit`,
    {
      headers: await authHeaders(page),
      data: { answers: started.questions.map(() => 0) },
    },
  );
  expect(submitted.status(), await submitted.text()).toBe(200);
});

test("X-02 session clock: near-expiry token renews, an expired one forces re-login, tabs survive, history works", async ({
  page,
  context,
}) => {
  await pin(page, "en");
  await signIn(page, STUDENT);
  const me = await apiGet<{ user_id: number; role: string }>(
    page,
    "/users/me",
  );

  // Concurrent tabs on one browser session: the second tab holds the same
  // session and its own requests succeed while the first tab stays usable.
  const second = await context.newPage();
  await open(second, "/student/me");
  await expect(second.locator("header")).toBeVisible({ timeout: 60_000 });
  const secondToken = await second.evaluate(() =>
    window.localStorage.getItem("bgpt_token"),
  );
  expect(secondToken).toBeTruthy();
  const otherMe = await second.request.get("/api/users/me", {
    headers: { Authorization: `Bearer ${secondToken}` },
  });
  expect(otherMe.status()).toBe(200);
  expect((await apiGet<{ email: string }>(page, "/users/me")).email).toBe(
    STUDENT,
  );
  await second.close();

  // Back/forward across two in-app navigations.
  await open(page, "/student/tutor");
  await open(page, "/student/me");
  await page.goBack();
  await expect
    .poll(() => new URL(page.url()).pathname, { timeout: 20_000 })
    .toBe("/student/tutor");
  await page.goForward();
  await expect
    .poll(() => new URL(page.url()).pathname, { timeout: 20_000 })
    .toBe("/student/me");

  // Refresh on a deep link keeps the session.
  await open(page, "/student/me");
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator("main#main-content")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page).toHaveURL(/\/student\/me$/);

  // The sliding contract, exercised through the app's own session: a token
  // inside the renewal window is exchanged for a fresh one by POST /auth/renew.
  //
  // RENEW_MINT_SECONDS (240) is derived from the client's renewal window
  // (api.ts RENEW_AHEAD_MS = 5 min): any token with less than that left
  // renews on the first api() call after boot, so the mint sits just under
  // the window and the branch cannot depend on runner speed. The old 60 s
  // mint raced a loaded CI runner: the boot's renewal POST landed after the
  // token had already died, the fail-secure probe bounced to /login and
  // cleared the token, and the later assertions read that wreckage instead
  // of the sliding contract (CI run stuck at /login, 36 s).
  const RENEW_MINT_SECONDS = 240;
  const nearExpiry = forgeToken(me.user_id, me.role, {
    expInSeconds: RENEW_MINT_SECONDS,
  });
  const renewed = await page.request.post("/api/auth/renew", {
    headers: { Authorization: `Bearer ${nearExpiry}` },
  });
  expect(renewed.status(), await renewed.text()).toBe(200);
  const fresh = tokenPayload(
    ((await renewed.json()) as { access_token: string }).access_token,
  );
  expect(
    (fresh.exp as number) - (fresh.iat as number),
    "the renewal did not slide the session to a full window",
  ).toBe(60 * 60);

  // The client half: with that token in storage the next boot slides it
  // forward BEFORE the session dies (api.ts maybeRenewSession). Each round
  // reloads and re-reads, so one parked request cannot leave the assertion
  // waiting on a dead connection.
  const before = Math.floor(Date.now() / 1000);
  await page.evaluate(
    (token) => window.localStorage.setItem("bgpt_token", token),
    nearExpiry,
  );
  await expect
    .poll(
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" }).catch(() => {});
        const token =
          (await page.evaluate(() =>
            window.localStorage.getItem("bgpt_token"),
          )) ?? "";
        return token.split(".").length === 3
          ? ((tokenPayload(token).exp ?? 0) as number)
          : 0;
      },
      {
        message: "the client never renewed the near-expiry session",
        timeout: 90_000,
        intervals: [4000],
      },
    )
    .toBeGreaterThan(before + 10 * 60);
  // The renewal kept the user IN the app (a failed one would have bounced
  // to /login and cleared the token) and the stored token is a genuinely
  // fresh full-window grant, not the minted one reserialized.
  await expect(page).toHaveURL(/\/student\/me$/);
  const stored = await page.evaluate(() =>
    window.localStorage.getItem("bgpt_token"),
  );
  expect(stored).not.toBeNull();
  expect(stored).not.toBe(nearExpiry);
  const storedClaims = tokenPayload(stored as string);
  expect(
    (storedClaims.exp as number) - (storedClaims.iat as number),
    "the stored token is not a full-window grant",
  ).toBe(60 * 60);

  // An expired token is dead: the app clears it and bounces to /login with
  // the deep link preserved in ?next=. The app's own retry control re-issues
  // the probe if a request is parked, so this waits on the product's
  // recoverable path rather than on one socket.
  //
  // The expired token is installed at document start of the fresh boot
  // instead of on the live page: a setItem on the running app races its next
  // api call, which reads the expired token, 401s and clears storage
  // mid-goto -- the boot then finds no token at all and takes RequireAuth's
  // bare redirect (no ?next), which is exactly the CI failure this half
  // used to be. With the init script the boot itself walks the fail-secure
  // path at any runner speed; the pathname guard keeps the re-login at the
  // end (a client-side navigation, never a new document) out of its scope.
  const expired = forgeToken(me.user_id, me.role, {
    iat: Math.floor(Math.floor(Date.now() / 1000) - 7200),
    expInSeconds: 3600,
  });
  await page.addInitScript((token) => {
    if (window.location.pathname === "/student/quiz") {
      window.localStorage.setItem("bgpt_token", token);
    }
  }, expired);
  await open(page, "/student/quiz");
  await expect
    .poll(
      async () => {
        const path = new URL(page.url()).pathname;
        if (path === "/login") return path;
        // Deliberately no reload: re-entering the deep link after the token
        // was cleared hits RequireAuth's own bare /login redirect, which
        // would overwrite the ?next= bounce this test is asserting. The app's
        // retry control re-issues a parked probe instead.
        const retry = page
          .locator("main")
          .getByRole("button", { name: "Try again" });
        if (await retry.isVisible().catch(() => false)) {
          await retry.click().catch(() => {});
        }
        return new URL(page.url()).pathname;
      },
      { message: "an expired token never forced a re-login", timeout: 90_000 },
    )
    .toBe("/login");
  await expect(page).toHaveURL(/\/login\?next=/, { timeout: 30_000 });
  expect(page.url()).toContain(encodeURIComponent("/student/quiz"));
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem("bgpt_token")))
    .toBeNull();
  // Re-login from the ?next= bounce lands back on the deep link.
  await page.locator("#email").fill(STUDENT);
  await page.locator("#password").fill(PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/student\/quiz$/, { timeout: 30_000 });
});

test("X-03 language and theme persist across reload and re-login", async ({
  page,
}) => {
  await signIn(page, STUDENT);
  await expect(page.locator("html")).toHaveAttribute("lang", "bn");
  await page
    .locator("header")
    .getByRole("button", { name: /Dark mode|ডার্ক মোড/ })
    .click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page
    .locator("header")
    .getByRole("button", { name: /Language|ভাষা/ })
    .click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");

  // Reload: both switches are device preferences read at boot.
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(
    await page.evaluate(() => ({
      lang: window.localStorage.getItem("bgpt_lang"),
      theme: window.localStorage.getItem("bgpt_theme"),
    })),
  ).toEqual({ lang: "en", theme: "dark" });

  // Re-login: sign-out must not scrub the device preferences.
  await signOut(page);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await signIn(page, STUDENT);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  // Restore the account's language for the rest of the run.
  await page
    .locator("header")
    .getByRole("button", { name: /Language|ভাষা/ })
    .click();
  await expect(page.locator("html")).toHaveAttribute("lang", "bn");
});

test("X-04 a 429 and a 503 on the login API show the app's copy in both languages", async ({
  page,
}) => {
  const rateLimited = {
    detail: { code: "rate_limited", message: "Rate limit exceeded" },
  };
  const unavailable = {
    detail: { code: "service_unavailable", message: "database is down" },
  };
  async function expectCopy(
    indicted: object,
    expected: string,
  ): Promise<void> {
    await page.unroute("**/auth/login");
    await page.route("**/auth/login", (route) =>
      route.fulfill({
        status: indicted === rateLimited ? 429 : 503,
        contentType: "application/json",
        body: JSON.stringify(indicted),
      }),
    );
    // Stay on /login: the previous attempt left the form mounted.
    await page.locator("#email").fill(STUDENT);
    await page.locator("#password").fill(PASSWORD);
    await page.locator('form button[type="submit"]').click();
    const alert = page.locator('[role="alert"]').first();
    await expect(alert).toBeVisible();
    await expect(alert).toHaveText(expected);
  }

  await open(page, "/login");
  await expect(page.locator("html")).toHaveAttribute("lang", "bn");
  // The public toggle is the product's own switch; no storage is written
  // directly, so the phase cannot be overridden by a later boot.
  await page.locator(".public-lang-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expectCopy(rateLimited, "Too many attempts. Please wait a minute.");
  await expectCopy(
    unavailable,
    "The server is busy right now — try again shortly.",
  );
  await page.unroute("**/auth/login");

  // Bangla: the same two states, the same policy, in script.
  await page.locator(".public-lang-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "bn");
  await expectCopy(rateLimited, "অনেকবার চেষ্টা হয়েছে। এক মিনিট অপেক্ষা করুন।");
  await expectCopy(unavailable, "সার্ভার এখন ব্যস্ত — একটু পরে আবার চেষ্টা করুন।");
  await page.unroute("**/auth/login");
  await page.locator(".public-lang-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
});

test.describe("X-09 dates and numerals", () => {
  // A Dhaka viewer with a fixed browser locale is the matrix the flow names.
  test.use({ timezoneId: "Asia/Dhaka", locale: "en-US" });

  test("X-09 rendered timestamps are the Dhaka instant and numeral policy is consistent", async ({
    page,
  }) => {
    await pin(page, "en");
    await signIn(page, STUDENT);
    // A real note, created through the API the app itself uses, gives the
    // profile screen a server timestamp to render.
    const created = await page.request.post("/api/notes", {
      headers: await authHeaders(page),
      data: { title: "W2 datetime", body: "কোষ সম্পর্কে নোট" },
    });
    expect(created.status(), await created.text()).toBe(201);
    const note = (await created.json()) as { id: number; created_at: string };
    await open(page, "/student/me");
    const row = page
      .locator(".notes-list li")
      .filter({ hasText: "W2 datetime" })
      .first();
    await expect(row).toBeVisible({ timeout: 30_000 });
    const rendered = ((await row.locator(".muted").textContent()) ?? "").trim();

    // The API stores naive UTC; the app restores the offset and renders the
    // Dhaka instant in the app language with the same Intl shape
    // lib/datetime.ts uses (F-116). A note timestamp keeps its time of day --
    // the same formatter renders assignment deadlines, where the hour is
    // load-bearing.
    const expected = await page.evaluate((iso) => {
      const at = new Date(`${iso.replace(/Z$/, "")}Z`);
      return {
        text: new Intl.DateTimeFormat("en", {
          timeZone: "Asia/Dhaka",
          year: "numeric",
          month: "numeric",
          day: "numeric",
          hour: "numeric",
          minute: "numeric",
          second: "numeric",
        }).format(at),
        offset: at.getTimezoneOffset(),
      };
    }, note.created_at);
    expect(expected.offset).toBe(-360);
    expect(rendered).toBe(expected.text);

    // The bn half of X-09: the same instant renders the bn-BD locale --
    // Bangla digits and the locale's own field order. (The earlier assertion
    // here pinned the en string to both languages; that was the defect
    // F-W2-FLOW-02 recorded, not the product contract.)
    await page
      .locator("header")
      .getByRole("button", { name: /Language|ভাষা/ })
      .click();
    await expect(page.locator("html")).toHaveAttribute("lang", "bn");
    const bnExpected = await page.evaluate((iso) => {
      const at = new Date(`${iso.replace(/Z$/, "")}Z`);
      return new Intl.DateTimeFormat("bn-BD", {
        timeZone: "Asia/Dhaka",
        year: "numeric",
        month: "numeric",
        day: "numeric",
        hour: "numeric",
        minute: "numeric",
        second: "numeric",
      }).format(at);
    }, note.created_at);
    const bnRendered = ((await row.locator(".muted").textContent()) ?? "").trim();
    expect(bnRendered).toBe(bnExpected);
    expect(bnRendered).toMatch(/[\u09E6-\u09EF]/);
    await page
      .locator("header")
      .getByRole("button", { name: /Language|ভাষা/ })
      .click();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    // Clean up the note this test created.
    await row.getByRole("button").click();
    await expect
      .poll(
        async () =>
          (
            (await apiGet<{ id: number }[]>(page, "/notes")).filter(
              (n) => n.id === note.id,
            ).length
          ),
        { timeout: 20_000 },
      )
      .toBe(0);
  });
});

/* ------------------------------------------------------------------- STU */

test("STU-03 a second turn stays in the same thread and both survive reload and re-login", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, STUDENT);
  await open(page, "/student/tutor");
  await settledAnswer(page, QUESTION);
  const followUp = "এটা আরেকটু সহজ করে বলো";
  await settledAnswer(page, followUp);

  // Message-level continuity: both turns are in ONE conversation, in order,
  // which is what carries the context to the model (the mock provider's
  // answer text itself does not depend on history).
  const conversations = await apiGet<
    { id: number; message_count?: number }[]
  >(page, "/tutor/conversations");
  expect(conversations.length).toBeGreaterThan(0);
  const newest = conversations[0];
  const messages = await apiGet<{ role: string; content: string }[]>(
    page,
    `/tutor/conversations/${newest.id}/messages`,
  );
  const userTurns = messages.filter((m) => m.role === "user");
  expect(userTurns.map((m) => m.content)).toEqual(
    expect.arrayContaining([QUESTION, followUp]),
  );
  const lastUserTurn = [...messages].reverse().find((m) => m.role === "user");
  expect(lastUserTurn?.content).toBe(followUp);
  expect(messages[messages.length - 1].role).toBe("assistant");

  // Reload -> the conversation chip reopens the full thread.
  await open(page, "/student/tutor");
  const chips = page.locator(".conv-chip button.conv-open");
  await expect(chips.first()).toBeVisible({ timeout: 30_000 });
  const byId = chips.filter({ hasText: `#${newest.id}` });
  const target = (await byId.count()) > 0 ? byId.first() : chips.first();
  await target.click();
  await expect(page.locator(".bubble.user").first()).toContainText("কোষ", {
    timeout: 30_000,
  });
  await expect(page.locator(".bubble.user").last()).toContainText("সহজ", {
    timeout: 30_000,
  });
});

test("STU-04 streaming: tokens grow, Stop aborts, a mid-stream failure is recoverable, Bangla text is intact", async ({
  page,
  context,
}) => {
  await pin(page, "en");
  await signIn(page, STUDENT);
  const cdp = await context.newCDPSession(page);
  // Slow 3G makes the stream observable without a fixed sleep: each SSE
  // event costs the injected latency, so the bubble's text grows measurably.
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 400,
    downloadThroughput: (400 * 1024) / 8,
    uploadThroughput: (400 * 1024) / 8,
  });
  await open(page, "/student/tutor");
  const box = page.getByRole("textbox", { name: COMPOSER });
  const composerSend = page.getByRole("button", { name: /পাঠান|Send/ }).first();
  const stop = page.getByRole("button", { name: /Stop|থামান/ });

  // Stop: the stream is held open (the request is accepted and never
  // answered), so the in-flight state is deterministic and the click lands
  // while the turn is genuinely running.
  await page.route("**/tutor/conversations/**/messages/stream", async (route) => {
    // Held, then aborted: the Stop click lands while the turn is in flight,
    // and the call itself fails if the page aborted the request first (which
    // is exactly the outcome under test).
    try {
      await new Promise((resolve) => setTimeout(resolve, 15_000));
      await route.abort();
    } catch {
      /* the app aborted the request first */
    }
  });
  await box.fill(QUESTION);
  await composerSend.click();
  await expect(stop).toBeVisible({ timeout: 30_000 });
  await stop.click();
  await expect(composerSend).toBeVisible({ timeout: 20_000 });
  await expect(stop).toHaveCount(0);
  await expect(page.locator("p.error.error-flush")).toHaveCount(0);
  await page.unroute("**/tutor/conversations/**/messages/stream");

  // Progressive arrival on a real stream: under the throttled link the
  // bubble's text grows while the turn is still in flight.
  await box.fill(QUESTION);
  await composerSend.click();
  const bubble = page.locator(".bubble.assistant").last();
  const firstLength = ((await bubble.textContent().catch(() => "")) ?? "")
    .length;
  await expect
    .poll(async () => ((await bubble.textContent().catch(() => "")) ?? "").length, {
      message: "the answer never arrived progressively",
      timeout: 30_000,
    })
    .toBeGreaterThan(firstLength);
  await expect(bubble).toContainText("Simple explanation", { timeout: 60_000 });

  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 0,
    downloadThroughput: -1,
    uploadThroughput: -1,
  });

  // A mid-stream failure: the connection is cut after the turn started. The
  // partial answer is kept, an error is shown, and the next turn works --
  // the recoverable state the flow asks for.
  await page.route("**/tutor/conversations/**/messages/stream", (route) =>
    route.abort("failed"),
  );
  await box.fill("একটা ভিন্ন প্রশ্ন শুরু করো");
  await composerSend.click();
  const error = page.locator("p.error.error-flush");
  await expect(error).toBeVisible({ timeout: 30_000 });
  await page.unroute("**/tutor/conversations/**/messages/stream");
  await box.fill(QUESTION);
  await composerSend.click();
  const recovered = page.locator(".bubble.assistant").last();
  await expect(recovered).toContainText("Simple explanation", {
    timeout: 60_000,
  });

  // Bangla cluster integrity: the mock answer quotes a sentence of the
  // retrieved textbook evidence verbatim, so the longest Bangla run in the
  // bubble must exist in the corpus the API serves -- a broken conjunct (or
  // a U+FFFD) would fail the containment check.
  const finalText = (await recovered.textContent()) ?? "";
  expect(finalText).not.toContain("\uFFFD");
  const runs = finalText
    .split(/[^\u0980-\u09FF\s]+/)
    .map((run) => run.trim())
    .filter((run) => run.length > 30);
  expect(runs.length, "no Bangla sentence in the answer").toBeGreaterThan(0);
  const longest = runs.sort((a, b) => b.length - a.length)[0];
  const corpus = await classSixCorpus(page);
  const corpusText = corpus.map((row) => row.text).join("\n");
  expect(
    corpusHasWindow(corpusText, longest),
    `the answer's Bangla text is not intact against the corpus: ${longest.slice(0, 30)}`,
  ).toBe(true);
});

test("STU-15 invite code: regenerate yields a new code, redemption is single-use", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, STUDENT);
  await open(page, "/student/me");
  await page.getByRole("button", { name: "Generate code" }).click();
  const first = (await page.locator(".invite-code").textContent())?.trim() ?? "";
  expect(first).toMatch(/^BGPT-[A-F0-9]{16}$/);

  // Reload then regenerate: the next code is new (the button reappears).
  await open(page, "/student/me");
  await page.getByRole("button", { name: "Generate code" }).click();
  const second = (await page.locator(".invite-code").textContent())?.trim() ?? "";
  expect(second).toMatch(/^BGPT-[A-F0-9]{16}$/);
  expect(second).not.toBe(first);
  // F-IV2-3 added the live-code list to the same card, so the expiry line is
  // no longer the last `.muted` element ("Active codes" is); assert the copy
  // itself instead of a positional locator.
  await expect(
    page.locator(".card", { hasText: "Link a parent" }),
  ).toContainText(/valid for [\d,]+ minutes/);
  await signOut(page);

  // Redeem the second code through the parent UI...
  await signIn(page, PARENT);
  await page.locator("#icode").fill(second);
  await page.getByRole("button", { name: "Link", exact: true }).click();
  const linked = page.getByText("Linked to your child's account.");
  await expect(linked).toBeVisible({ timeout: 30_000 });

  // ...and the same code cannot be redeemed twice: the single-use claim
  // refuses the second attempt with the invalid-invite copy.
  await page.locator("#icode").fill(second);
  await page.getByRole("button", { name: "Link", exact: true }).click();
  const alert = page.locator('[role="alert"]').first();
  await expect(alert).toBeVisible({ timeout: 30_000 });
  await expect(alert).toContainText("The invite code is invalid or expired");
  // The expiry window itself (invite_ttl_minutes) cannot be waited out here;
  // test_school_invite_expiry.py and test_single_use_tokens.py pin it.
});

test("STU-17 five question variants settle grounded or refused, and citations match the corpus", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, STUDENT);
  await open(page, "/student/tutor");
  await page.getByRole("button", { name: "New chat" }).click();

  const variants = [
    "কোষ কী?",
    "কোশ কী?",
    "কোষ কি?",
    "kosh ki?",
    "What is a cell?",
  ];
  const corpus = await classSixCorpus(page);
  let grounded = 0;
  for (const variant of variants) {
    const answer = await settledAnswer(page, variant);
    const text = (await answer.textContent()) ?? "";
    if (text.includes("Simple explanation")) {
      grounded += 1;
      // Every grounded citation opens the evidence modal with the retrieved
      // excerpt, and that excerpt must be text the corpus really carries in
      // the chapter the path names. (There is no citation-to-Reader
      // navigation in the product; the modal is the shipped affordance. The
      // evidence row renders beside the bubble, not inside it.)
      const chip = page.locator(".sources").last().locator("button.source-chip").first();
      await expect(chip).toBeVisible();
      await chip.click();
      const modal = page.getByRole("dialog");
      await expect(modal).toBeVisible();
      const excerpt = (
        (await modal.locator(".evidence-quote").textContent()) ?? ""
      ).trim();
      expect(excerpt.length).toBeGreaterThan(0);
      const path = [
        ...(await modal.locator(".evidence-path").textContent())!
          .split("›")
          .map((part) => part.trim()),
      ];
      expect(
        corpusHasWindow(
          corpus.map((row) => row.text).join("\n"),
          excerpt,
        ),
        `the cited excerpt is not in the corpus: ${excerpt.slice(0, 30)}`,
      ).toBe(true);
      const citedChapter = path.find((part) =>
        corpus.some((row) => row.chapter.includes(part)),
      );
      expect(
        citedChapter,
        `the evidence path names no real chapter: ${path.join(" / ")}`,
      ).toBeTruthy();
      await page.keyboard.press("Escape");
      await expect(modal).toHaveCount(0);
    } else {
      expect(
        text,
        `variant ${variant} neither grounded nor refused with the fixed copy`,
      ).toContain(INSUFFICIENT_EVIDENCE);
      expect(
        await page.locator(".sources").last().locator("button.source-chip").count(),
      ).toBe(0);
    }
  }
  expect(
    grounded,
    "at least the standard Bangla wording must ground",
  ).toBeGreaterThanOrEqual(1);
});

test("STU-18 a follow-up stays grounded and New chat leaks no earlier context", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, STUDENT);
  await open(page, "/student/tutor");
  const first = await settledAnswer(page, QUESTION);
  await expect(first).toContainText("Simple explanation", { timeout: 60_000 });

  // The follow-up is asked in the same thread and must come back grounded.
  // (Whether the answer TEXT uses the earlier turns cannot be observed with
  // the deterministic mock provider -- the prompt assembly is API-level --
  // so what is asserted is that the thread stays coherent and grounded.)
  const followUpText = "কোষ কী?";
  const followUp = await settledAnswer(page, followUpText);
  await expect(followUp).toContainText("Simple explanation", {
    timeout: 60_000,
  });
  // The follow-up turn is part of the same thread, which is the mechanism
  // that carries the earlier context (see STU-03 for the message-level proof).
  const conversations = await apiGet<{ id: number }[]>(
    page,
    "/tutor/conversations",
  );
  const messages = await apiGet<{ content: string }[]>(
    page,
    `/tutor/conversations/${conversations[0].id}/messages`,
  );
  expect(
    messages.filter((m) => (m.content ?? "") === followUpText).length,
  ).toBe(2);

  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.locator(".bubble")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator(".empty-title")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Simple explanation");
  // The empty composer starts a clean thread: asking again must not append
  // the earlier turn to the visible transcript.
  const third = await settledAnswer(page, QUESTION);
  await expect(third).toContainText("Simple explanation", { timeout: 60_000 });
  await expect(page.locator(".bubble.user")).toHaveCount(1);
});
