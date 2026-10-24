import { expect, test, type Page } from "@playwright/test";

/**
 * The critical user journeys, in a real browser (restored from a1929ad,
 * adapted to this branch's UI and the coverage-gated mock corpus).
 *
 * Every test drives the shipped UI against the real API (mock LLM provider,
 * seeded role accounts -- see seed_e2e_users.py). If a route guard, the auth
 * flow, the /api proxy, the invite-code flow or a dashboard's first data
 * fetch breaks, one of these fails. No fixed sleeps: everything waits on a
 * real signal (URL, visible bubble, table cell) via Playwright's auto-waiting.
 *
 * Corpus reality on this branch: the bundled sample corpus carries
 * class 6-10 science/math/bangla chapters, and every ask is coverage-gated.
 * A class-6 science question about কোষ (the cell) grounds fine; a question
 * the corpus cannot evidence is REFUSED with a fixed Bengali sentence --
 * the refusal is asserted as a first-class outcome, not worked around.
 */

const PASSWORD = "E2ePass!2345";
const STUDENT = "student1@e2e.test";
const TEACHER = "teacher1@e2e.test";
const PARENT = "parent1@e2e.test";
const ADMIN = "admin1@e2e.test";

// The app defaults to Bangla; pin English so the selectors below are stable
// and a missing translation key still renders (i18n is covered by unit tests).
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    window.localStorage.setItem("bgpt_lang", "en"),
  );
});

// `load` also waits for the font files; `domcontentloaded` is enough for the
// React mount, and every assertion below waits on a real DOM signal anyway.
async function open(page: Page, path: string): Promise<void> {
  await page.goto(path, { waitUntil: "domcontentloaded" });
}

async function signIn(page: Page, email: string): Promise<void> {
  await open(page, "/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.locator('form button[type="submit"]').click();
  // Wait for the SESSION, not just the click. The role router leaves /login
  // only after the token is stored; a test that navigates in the gap gets
  // bounced by the auth guard -- the parent-invite journey raced exactly
  // there in the first CI run of this suite (/login snapshot after signIn).
  await expect(page).not.toHaveURL(/\/login$/);
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem("bgpt_token")))
    .toBeTruthy();
}

async function signOut(page: Page): Promise<void> {
  // Scoped to the shell header: MePage also carries a labelled logout button,
  // so a page-wide role query is ambiguous (strict-mode violation) on that
  // route. The button's name is the i18n key `logout` ("Log out").
  await page
    .locator("header")
    .getByRole("button", { name: "Log out" })
    .click();
  await expect(page).toHaveURL(/\/login$/);
}

test("a student signs in, is routed to the student home and can log out", async ({
  page,
}) => {
  await signIn(page, STUDENT);

  // Role-based landing page, not just "login returned 200".
  await expect(page).toHaveURL(/\/student$/);
  expect(
    await page.evaluate(() => window.localStorage.getItem("bgpt_token")),
  ).toBeTruthy();

  await signOut(page);
  // Sign-out must wipe the shared-device token, not only navigate.
  expect(
    await page.evaluate(() => window.localStorage.getItem("bgpt_token")),
  ).toBeNull();
  // The app shell is gone: the login form is reachable again.
  await expect(page.locator("#email")).toBeVisible();
});

test("a guardian-consented student registers and lands on the student home", async ({
  page,
}) => {
  // One registration per run: /auth/register is per-IP limited to 10/min
  // (F-076) and each call runs Argon2id. The email is timestamped because a
  // re-run against a reused harness API keeps the previous account row
  // (the API answers email_taken with a 409).
  const email = `reg-${Date.now()}@e2e.test`;
  await open(page, "/register");
  await page.locator("#name").fill("E2E Registered");
  await page.locator("#remail").fill(email);
  await page.locator("#rpassword").fill(PASSWORD);
  // role defaults to student (RegisterPage state), which reveals the class
  // picker and the guardian-consent checkbox this branch requires: the API
  // rejects a student registration without guardian_consent (409), so this
  // journey is also the proof the UI sends it.
  await page.locator("#consent").check();
  await page.locator('form button[type="submit"]').click();

  // RegisterPage signs the fresh account in when SMTP is unconfigured (the
  // harness API has no SMTP), so the journey ends on the role home.
  await expect(page).toHaveURL(/\/student$/, { timeout: 30_000 });
  await expect(
    await page.evaluate(() => window.localStorage.getItem("bgpt_token")),
  ).toBeTruthy();
});

test("a student asks the tutor and gets a streamed mock answer", async ({
  page,
}) => {
  await signIn(page, STUDENT);
  await expect(page).toHaveURL(/\/student$/);

  await open(page, "/student/tutor");
  const ask = page.getByRole("textbox", {
    name: "Ask anything from your textbook…",
  });
  await ask.fill("কোষ কী?");
  await page.getByRole("button", { name: "Send" }).click();

  // The answer arrives over SSE. The mock provider quotes retrieved textbook
  // text in the four-section teaching layout, and the page parses the
  // section markers and re-labels them in the UI language -- "Simple
  // explanation" is the saSimple heading, and কোষ is the retrieved science
  // text itself, so this asserts the stream completed, the sectioned layout
  // rendered AND retrieval surfaced real evidence for the question.
  const answer = page.locator(".bubble.assistant").last();
  await expect(answer).toContainText("Simple explanation", { timeout: 60_000 });
  await expect(answer).toContainText("কোষ");

  // The answer's interaction surface is present in a real browser right
  // after the stream completes: the evidence row carries the source chips
  // (openable, dialog covered by keyboard.spec.ts), and the same row mounts
  // the rating, reteach, save and regenerate controls. The full behaviours
  // behind these controls are pinned by the unit suites; these are the e2e
  // half that proves the controls actually mount on the shipped page.
  const sources = page.locator(".sources").last();
  await expect(sources).toBeVisible();
  await expect(sources.locator("button.source-chip").first()).toBeVisible();
  await expect(
    sources.getByRole("button", { name: "Save as note" }),
  ).toBeVisible();
  await expect(sources.getByText("Regenerate")).toBeVisible();
});

test("an out-of-corpus question is refused with the grounding message", async ({
  page,
}) => {
  await signIn(page, STUDENT);
  await open(page, "/student/tutor");
  const ask = page.getByRole("textbox", {
    name: "Ask anything from your textbook…",
  });
  // Today's weather is evidence-proof by construction: no bundled chapter
  // can cover it, so the coverage gate refuses with its fixed copy. The UI
  // renders the refusal as a normal assistant turn -- a calm in-product
  // answer, never an error page or a fabricated one.
  await ask.fill("আজ ঢাকায় বৃষ্টি হবে কি আবহাওয়া অফিস বলো?");
  await page.getByRole("button", { name: "Send" }).click();

  const answer = page.locator(".bubble.assistant").last();
  // The refusal sentence is API-owned Bengali copy (INSUFFICIENT_EVIDENCE_ANSWER)
  // -- it does not translate with the UI language.
  await expect(answer).toContainText("পাঠ্যবইয়ের সংশ্লিষ্ট অধ্যায়", {
    timeout: 60_000,
  });
  // A refused turn must not dress itself up as sourced: no evidence row, no
  // chips, no reteach offer on that bubble.
  await expect(answer.locator(".sources")).toHaveCount(0);
});

test("a student completes a quiz attempt end to end", async ({ page }) => {
  await signIn(page, STUDENT);
  await open(page, "/student/quiz");

  // Generate a mock quiz (default subject, 5 questions) and start it.
  await page.getByRole("button", { name: "Start quiz" }).click();
  const question = page.locator(".quiz-q-title").first();
  await expect(question).toBeVisible({ timeout: 60_000 });

  // Answer the questions: pick the first option of each, walking with the
  // pager's Next button, then submit. The mock generator always supplies
  // options, so the first option is a stable, honest selection.
  for (;;) {
    await page.locator("button.quiz-option").first().click();
    const next = page.getByRole("button", { name: "Next question" });
    if (await next.isVisible().catch(() => false)) {
      await next.click();
      await expect(page.locator(".quiz-q-title").first()).toBeVisible();
    } else {
      break;
    }
  }
  await page.getByRole("button", { name: "Finish quiz" }).click();

  // The graded result screen replaces the question view: the result heading
  // and the rounded score percentage are rendered from the submit response.
  await expect(page.locator(".quiz-q")).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: /quiz result/i })).toBeVisible();
  await expect(page.locator("strong", { hasText: "%" }).first()).toBeVisible();
});

test("a teacher signs in and sees the teacher dashboard", async ({ page }) => {
  await signIn(page, TEACHER);

  await expect(page).toHaveURL(/\/teacher$/);
  await expect(page.getByText("Teacher dashboard")).toBeVisible();
  // The dashboard's own data fetch resolved (stats card, not a permanent
  // "loading" skeleton): the greeting is rendered from /users/me.
  await expect(page.locator("h2").first()).toContainText("E2E Teacher");
});

test("a student generates a parent invite code and the parent links with it", async ({
  page,
}) => {
  // Student side: the code is a real product feature in MePage.
  await signIn(page, STUDENT);
  await open(page, "/student/me");
  await page.getByRole("button", { name: "Generate code" }).click();
  const code = (await page.locator(".invite-code").textContent())?.trim() ?? "";
  expect(code).toMatch(/^BGPT-[A-Z0-9]+$/);

  await signOut(page);

  // Parent side: redeem the code in the parent dashboard.
  await signIn(page, PARENT);
  await expect(page).toHaveURL(/\/parent$/);
  await page.locator("#icode").fill(code);
  await page.getByRole("button", { name: "Link" }).click();

  await expect(page.getByText("Linked to your child's account.")).toBeVisible();
  // The children table is fed by /parents/me/children: the link is real.
  const row = page.locator("table tbody tr", { hasText: "E2E Student" });
  await expect(row).toHaveCount(1);
});

test("an admin signs in and sees the admin dashboard", async ({ page }) => {
  await signIn(page, ADMIN);

  await expect(page).toHaveURL(/\/admin$/);
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }).first(),
  ).toBeVisible();
});
