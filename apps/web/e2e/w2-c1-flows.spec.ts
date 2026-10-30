import { expect, test, type Page } from "@playwright/test";
import {
  COMPOSER_LABEL,
  openRoute,
  PASSWORD,
  signIn,
  useVariant,
} from "./a11y";

/**
 * Wave 2 flow execution, stream C1: the STU rows the audit left PARTIAL.
 *
 *  * STU-06 — an unsafe prompt gets a supportive refusal and nothing harmful
 *    is persisted (the stored assistant turn is the refusal copy, and the
 *    refusal audit row carries counts, not content).
 *  * STU-07 — an image question drives all four attachment cases: a valid
 *    PNG, a wrong type, an oversized file and a corrupted payload.
 *  * STU-10 — the revision mini-quiz drains a due item, and the streak
 *    heatmap's rendered summary equals the activity API's own numbers.
 *  * STU-11 — the reader: chapter open, bookmark, font scale, TTS toggle,
 *    offline copy lifecycle, and the quiz "explain this" deep link.
 *  * STU-12 — unified search returns the same hits for three Bangla surface
 *    forms of one word and offers the ask-in-Tutor action for a question.
 *
 * Harness: real UI against the real API with LLM_PROVIDER=mock (see
 * playwright.config.ts). No HTTP mocking except the state fixtures the API
 * itself offers; no fixed sleeps. Console errors fail every test (FE-15).
 */

test.describe.configure({ timeout: 5 * 60_000 });

const STUDENT = "student1@e2e.test";
const PASSWORD_E2E = PASSWORD;

/** The one known in-corpus chapter (class-6 science, bundled sample corpus). */
const CHAPTER = "কোষ";
const SUBJECT = "science";

function collectConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    if (/Failed to load resource/i.test(msg.text())) return;
    errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return errors;
}

async function apiToken(page: Page): Promise<string> {
  const token = await page.evaluate(() =>
    window.localStorage.getItem("bgpt_token"),
  );
  expect(token).toBeTruthy();
  return token as string;
}

function authHeader(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

async function openTutor(page: Page): Promise<void> {
  await openRoute(page, "/student/tutor");
  await expect(page.getByLabel(COMPOSER_LABEL)).toBeVisible({
    timeout: 30_000,
  });
}

async function ask(page: Page, question: string): Promise<void> {
  const composer = page.getByLabel(COMPOSER_LABEL);
  await composer.fill(question);
  await composer.press("Enter");
}

/** Wait for an assistant bubble whose text contains `needle`. */
async function expectAssistantText(page: Page, needle: string) {
  await expect(page.locator(".bubble.assistant").last()).toContainText(needle, {
    timeout: 60_000,
  });
}

/* ----------------------------------------------------------------- STU-06 */

test("STU-06 an unsafe prompt gets the supportive refusal and nothing harmful is stored", async ({
  page,
}) => {
  const errors = collectConsole(page);
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT);
  const token = await apiToken(page);

  await openTutor(page);
  // A self-harm disclosure in the student's own words; the deterministic
  // screen refuses it (services/safety.py).
  await ask(page, "আমি বাঁচতে চাই না");
  const bubble = page.locator(".bubble.assistant").last();
  await expectAssistantText(page, "গুরুত্বপূর্ণ");
  // Supportive copy, not a lecture: the government helplines are present.
  await expect(bubble).toContainText("১৬২৬৩");
  await expect(bubble).toContainText("৯৯৯");
  // The turn is marked unsupported (not a textbook answer).
  await expect(page.locator(".bubble.assistant").last()).toBeVisible();
  await expect(page.locator(".sources").last()).toContainText("প্রমাণ নেই");

  // Persistence: the stored assistant turn is the refusal copy itself.
  const convs = await page.request.get("/api/tutor/conversations", {
    headers: authHeader(token),
  });
  expect(convs.status()).toBe(200);
  const list = (await convs.json()) as Array<{ id: number }>;
  expect(list.length).toBeGreaterThan(0);
  const messages = await page.request.get(
    `/api/tutor/conversations/${list[0].id}/messages`,
    { headers: authHeader(token) },
  );
  expect(messages.status()).toBe(200);
  const rows = (await messages.json()) as Array<{
    role: string;
    content: string;
    refused_reason?: string | null;
  }>;
  const stored = rows.filter((r) => r.role === "assistant").at(-1);
  expect(stored, "the assistant turn was persisted").toBeTruthy();
  expect(stored?.refused_reason).toBe("self_harm");
  expect(stored?.content).toContain("গুরুত্বপূর্ণ");
  expect(stored?.content).toContain("১৬২৬৩");

  // The audit row behind the refusal board carries the reason and class,
  // never the question text (safety_v2's privacy contract).
  const adminLogin = await page.request.post("/api/auth/login", {
    headers: { "Content-Type": "application/json" },
    data: { email: "admin1@e2e.test", password: PASSWORD_E2E },
  });
  expect(adminLogin.status()).toBe(200);
  const adminToken = ((await adminLogin.json()) as { access_token: string })
    .access_token;
  const audit = await page.request.get("/api/admin/safety/refusals", {
    headers: authHeader(adminToken),
  });
  expect(audit.status()).toBe(200);
  const auditBody = await audit.text();
  expect(auditBody).toContain("self_harm");
  expect(auditBody).not.toContain("বাঁচতে চাই না");

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

/* ----------------------------------------------------------------- STU-07 */

const PNG_1PX =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

test("STU-07 image question: valid, wrong-type, oversized and corrupted attachments", async ({
  page,
}) => {
  const errors = collectConsole(page);
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT);
  await openTutor(page);

  const fileInput = page.locator('input[type="file"]');
  const errorLine = page.locator("p.error");

  // ── wrong type: refused client-side with the read/type error, never the
  // "too large" copy (F-202), and no stream request leaves the page. ──────
  let streamRequests = 0;
  page.on("request", (req) => {
    if (req.url().includes("/messages/stream")) streamRequests += 1;
  });
  await fileInput.setInputFiles({
    name: "homework.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("not an image"),
  });
  await expect(errorLine).toContainText("পড়া যায়নি");
  await expect(errorLine).not.toContainText("বড়");
  expect(streamRequests).toBe(0);

  // ── oversized: a real PNG padded past the 1.5 MB bound ────────────────
  await fileInput.setInputFiles({
    name: "huge.png",
    mimeType: "image/png",
    buffer: Buffer.concat([
      Buffer.from(PNG_1PX, "base64"),
      Buffer.alloc(1_600_000, 7),
    ]),
  });
  await expect(errorLine).toContainText("বড়");
  expect(streamRequests).toBe(0);

  // ── valid: preview appears, an intent chip sends the image turn ───────
  await fileInput.setInputFiles({
    name: "question.png",
    mimeType: "image/png",
    buffer: Buffer.from(PNG_1PX, "base64"),
  });
  await expect(page.locator(".attach-preview")).toBeVisible();
  await page.getByRole("button", { name: "সমাধান করো" }).click();
  // The mock provider cannot see images; the honest refusal is the answer.
  await expectAssistantText(page, "ছবি থেকে উত্তর দেওয়া এখনো সম্ভব হয়নি");
  expect(streamRequests).toBeGreaterThan(0);

  // ── corrupted: right type and size, undecodable bytes → server 422 ────
  const before = streamRequests;
  await fileInput.setInputFiles({
    name: "broken.png",
    mimeType: "image/png",
    buffer: Buffer.from("this is not a png at all"),
  });
  await expect(page.locator(".attach-preview")).toBeVisible();
  await page.getByRole("button", { name: "সমাধান করো" }).click();
  await expect(errorLine).toContainText("পড়া যায়নি", { timeout: 60_000 });
  expect(streamRequests).toBeGreaterThan(before);

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

/* ----------------------------------------------------------------- STU-10 */

test("STU-10 revision mini-quiz drains a due item and the heatmap matches activity", async ({
  page,
}) => {
  const errors = collectConsole(page);
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT);
  const token = await apiToken(page);
  const me = (await (
    await page.request.get("/api/users/me", { headers: authHeader(token) })
  ).json()) as { profile_id: number };

  // State fixture through the API the UI itself uses: a fully wrong attempt
  // seeds the spaced-revision queue and today's activity.
  const started = await page.request.post("/api/quizzes", {
    headers: { ...authHeader(token), "Content-Type": "application/json" },
    data: {
      student_id: me.profile_id,
      class_level: 6,
      subject: "science",
      num_questions: 5,
    },
  });
  expect(started.status()).toBe(200);
  const attempt = (await started.json()) as {
    attempt_id: number;
    questions: unknown[];
  };
  const submitted = await page.request.post(
    `/api/quizzes/${attempt.attempt_id}/submit`,
    {
      headers: { ...authHeader(token), "Content-Type": "application/json" },
      data: { answers: attempt.questions.map(() => -1) },
    },
  );
  expect(submitted.status()).toBe(200);

  // ── the revision tab shows the due item and answering drains it ────────
  const due = (await (
    await page.request.get("/api/revision/due", { headers: authHeader(token) })
  ).json()) as {
    due_count: number;
    items: Array<{
      id: number;
      question: string;
      options: string[];
      correct_index: number;
    }>;
  };
  expect(due.due_count).toBeGreaterThan(0);
  const item = due.items[0];

  await openRoute(page, "/student/quiz");
  const revisionTab = page.getByRole("tab", { name: /রিভিশন|Revision/ });
  await revisionTab.click();
  await expect(page.getByText(item.question).first()).toBeVisible({
    timeout: 30_000,
  });
  await page
    .getByRole("button", {
      name: item.options[item.correct_index],
      exact: true,
    })
    .first()
    .click();
  // The correct answer schedules the item into the future: it leaves the
  // due queue both on screen and in the API.
  await expect(page.getByText(item.question).first()).toHaveCount(0, {
    timeout: 30_000,
  });
  await expect
    .poll(async () => {
      const now = (await (
        await page.request.get("/api/revision/due", {
          headers: authHeader(token),
        })
      ).json()) as { items: Array<{ id: number }> };
      return now.items.some((i) => i.id === item.id);
    })
    .toBe(false);

  // ── the heatmap is the activity data, recomputed in the test ──────────
  const activity = (await (
    await page.request.get(`/api/students/${me.profile_id}/activity`, {
      headers: authHeader(token),
    })
  ).json()) as {
    streak: number;
    days: Array<{ date: string; questions: number; quizzes: number }>;
  };
  const totals = activity.days.reduce(
    (acc, d) => {
      acc.questions += d.questions;
      acc.active += d.questions + d.quizzes > 0 ? 1 : 0;
      return acc;
    },
    { questions: 0, active: 0 },
  );
  // The fixture must be visible: today's quiz is one active day.
  expect(totals.active).toBeGreaterThan(0);
  expect(activity.days.some((d) => d.quizzes >= 1)).toBe(true);

  await openRoute(page, "/student/me");
  const heatmap = page.getByTestId("activity-heatmap");
  await expect(heatmap).toBeVisible({ timeout: 30_000 });
  const label = (await heatmap.getAttribute("aria-label")) ?? "";
  const nums = [...label.matchAll(/\d+/g)].map((m) => Number(m[0]));
  expect(nums[0], `heatmap days in "${label}"`).toBe(activity.days.length);
  expect(nums[1], `heatmap questions in "${label}"`).toBe(totals.questions);
  expect(nums[2], `heatmap active days in "${label}"`).toBe(totals.active);
  await expect(
    page.getByText(`${activity.streak} দিনের ধারাবাহিকতা`),
  ).toBeVisible();

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

/* ----------------------------------------------------------------- STU-11 */

const READER_ROUTE = `/student/learn/${SUBJECT}/${encodeURIComponent(CHAPTER)}?class=6`;

test("STU-11 reader: chapter opens, bookmark and font scale persist, TTS toggles", async ({
  page,
}) => {
  const errors = collectConsole(page);
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT);

  await openRoute(page, READER_ROUTE);
  // The chapter's own title is the page h1 and the first section is rendered.
  await expect(page.locator("h1.reader-title")).toHaveText(CHAPTER, {
    timeout: 30_000,
  });
  await expect(page.locator(".reader-md")).toContainText("কোষঝিল্লি");

  // ── bookmark: toggles and survives a reload (server-backed) ───────────
  const bookmark = page.getByRole("button", { name: "বুকমার্ক" });
  await expect(bookmark).toHaveAttribute("aria-pressed", "false");
  await bookmark.click();
  await expect(bookmark).toHaveAttribute("aria-pressed", "true");
  await openRoute(page, READER_ROUTE);
  await expect(page.getByRole("button", { name: "বুকমার্ক" })).toHaveAttribute(
    "aria-pressed",
    "true",
    { timeout: 30_000 },
  );

  // ── font scale: 1.4em on the article, persisted as a device preference ─
  const range = page.locator('input[type="range"]');
  const articlePx = async () =>
    parseFloat(
      await page
        .locator(".reader-md")
        .evaluate((el) => getComputedStyle(el).fontSize),
    );
  const basePx = await articlePx();
  await range.fill("1.4");
  await expect.poll(articlePx).toBeCloseTo(basePx * 1.4, 0);
  expect(await page.evaluate(() => localStorage.getItem("fontScale"))).toBe(
    "1.4",
  );
  await openRoute(page, READER_ROUTE);
  await expect(page.locator('input[type="range"]')).toHaveValue("1.4");
  await expect.poll(articlePx).toBeCloseTo(basePx * 1.4, 0);

  // ── TTS: the control is present (Chromium has speechSynthesis), toggling
  // it must not throw and must return to the idle state. A device with no
  // Bangla voice is beyond a headless browser; the fallback branch is
  // unit-covered (progress.test / workspace.test). ───────────────────────
  const listen = page.getByRole("button", { name: "শুনুন" });
  await expect(listen).toHaveAttribute("aria-pressed", "false");
  await listen.click();
  // Chromium without voices still reports speechSynthesis, so the control
  // may toggle on and immediately fall back to idle; either way the press
  // must not throw and the idle label must return.
  if ((await listen.getAttribute("aria-pressed")) === "true") {
    await listen.click();
  }
  await expect(listen).toHaveAttribute("aria-pressed", "false");

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

test("STU-11 the offline copy appears in the library and can be deleted", async ({
  page,
}) => {
  const errors = collectConsole(page);
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT);

  await openRoute(page, READER_ROUTE);
  const download = page.getByRole("button", { name: "ডাউনলোড করুন" });
  await expect(download).toBeVisible({ timeout: 30_000 });
  await download.click();
  // F-203: the saved state is exposed to assistive tech, not just painted.
  await expect(download).toHaveAttribute("aria-pressed", "true");

  // Manage-downloads: the copy is listed with its size and can be deleted.
  await openRoute(page, "/student/learn");
  const library = page.getByText("অফলাইন কপি · 1");
  await expect(library).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: `মুছে ফেলুন: ${CHAPTER}` }).click();
  await expect(page.getByText("অফলাইন কপি · 1")).toHaveCount(0);

  // And the reader agrees: the copy is gone, so the control is idle again.
  await openRoute(page, READER_ROUTE);
  await expect(
    page.getByRole("button", { name: "ডাউনলোড করুন" }),
  ).toHaveAttribute("aria-pressed", "false", { timeout: 30_000 });

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

test("STU-11 the quiz's explain-this deep link lands in the tutor with the question pre-asked", async ({
  page,
}) => {
  const errors = collectConsole(page);
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT);

  // A UI-driven quiz, finished with every item unanswered: the app confirms
  // once, then submits -1 for all — deterministic wrong items with explain
  // links, without relying on which option happens to be correct.
  await openRoute(page, "/student/quiz");
  const start = page
    .getByRole("button", { name: /কুইজ শুরু|শুরু করুন|Start/i })
    .first();
  await expect(start).toBeVisible({ timeout: 30_000 });
  await start.click();
  const finish = page.getByRole("button", { name: "শেষ করুন" });
  await expect(finish).toBeVisible({ timeout: 30_000 });
  await finish.click();
  // The unanswered confirmation appears; confirm it.
  const confirm = page.getByRole("button", { name: "যা আছে তা-ই জমা দিন" });
  await expect(confirm).toBeVisible({ timeout: 20_000 });
  await confirm.click();
  await expect(page.getByText("আপনার কুইজ ফলাফল")).toBeVisible({
    timeout: 60_000,
  });

  const explain = page.getByRole("button", { name: "বুঝিয়ে দিন" }).first();
  await expect(explain).toBeVisible();
  await explain.click();
  await expect(page).toHaveURL(/\/student\/tutor$/);
  // The tutor asks the composed explain question itself (location.state).
  await expect(page.locator(".bubble.user").last()).toContainText(
    "আমি কুইজে এই প্রশ্নে ভুল করেছি",
    { timeout: 30_000 },
  );
  await expect(page.locator(".bubble.assistant").last()).not.toBeEmpty({
    timeout: 60_000,
  });
  // The back-link returns to the stored result screen.
  await page.getByRole("button", { name: "কুইজের ফলাফলে ফিরে যান" }).click();
  await expect(page).toHaveURL(/\/student\/quiz\?result=1$/);
  await expect(page.getByText("আপনার কুইজ ফলাফল")).toBeVisible({
    timeout: 30_000,
  });

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

/* ----------------------------------------------------------------- STU-12 */

test("STU-12 unified search: three Bangla surface forms return the same hits", async ({
  page,
}) => {
  const errors = collectConsole(page);
  await useVariant(page, { theme: "light", lang: "bn" });
  await signIn(page, STUDENT);
  await openRoute(page, "/student");

  const search = page.getByRole("combobox");
  await search.click();

  // Forms of one in-corpus word the normalizer must fold together:
  //  * the plain form;
  //  * an invisible ZWNJ between clusters (mobile keyboards insert them);
  //  * the decomposed vowel sign (U+09C7 + U+09BE) instead of U+09CB.
  const plain = "কোষ"; // ক ো ষ (U+0995 U+09CB U+09B7)
  const zwnj = "কো‌ষ"; // the plain form with a ZWNJ after the vowel sign
  const decomposed = "কোষ"; // U+09C7 + U+09BE instead of the U+09CB sign
  expect(new Set([plain, zwnj, decomposed]).size).toBe(3);
  expect(zwnj.normalize("NFKC")).toBe(plain);
  expect(decomposed.normalize("NFKC")).toBe(plain);

  async function hitTitles(query: string): Promise<string[]> {
    await search.fill(query);
    const listbox = page.getByRole("listbox");
    await expect(listbox).toBeVisible({ timeout: 20_000 });
    return (await listbox.getByRole("option").allInnerTexts()).map((t) =>
      t.replace(/\s+/g, " ").trim(),
    );
  }

  const base = await hitTitles(plain);
  expect(base.length, "the plain form finds the chapter").toBeGreaterThan(0);
  expect(base.join("\n")).toContain("কোষ");
  const withZwnj = await hitTitles(zwnj);
  const withDecomposed = await hitTitles(decomposed);
  expect(withZwnj).toEqual(base);
  expect(withDecomposed).toEqual(base);

  // The unified part: a question-shaped query offers "ask in Tutor" and the
  // hand-off actually opens the tutor with the question pre-asked.
  await search.fill("কোষ কী?");
  const askOption = page.locator("#search-option-ask");
  await expect(askOption).toBeVisible({ timeout: 20_000 });
  await askOption.click();
  await expect(page).toHaveURL(/\/student\/tutor$/);
  await expect(page.locator(".bubble.user").last()).toContainText("কোষ কী?", {
    timeout: 30_000,
  });
  await expect(page.locator(".bubble.assistant").last()).not.toBeEmpty({
    timeout: 60_000,
  });

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

/* ----------------------------------------------------------------- FE-05 */

/** Every client source file whose call helpers count as API traffic. */
function clientSources(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!["node_modules", "test"].includes(entry.name))
        clientSources(path, out);
    } else if (/\.(ts|tsx)$/.test(entry.name)) {
      out.push(path);
    }
  }
  return out;
}

test("FE-05 every client call exists in the served OpenAPI schema", async ({
  page,
}) => {
  const calls = extractClientCalls(
    clientSources("src")
      .map((file) => readFileSync(file, "utf8"))
      .join("\n"),
  );
  // A frozen extractor (regex rot) would make this check vacuous.
  expect(
    calls.length,
    "the extractor found the client's calls",
  ).toBeGreaterThan(60);
  const schemaRes = await page.request.get("/api/openapi.json");
  expect(schemaRes.status()).toBe(200);
  const schema = (await schemaRes.json()) as OpenApiSchema;
  // 120-route API; a schema that failed to mount would pass an empty compare.
  expect(Object.keys(schema.paths ?? {}).length).toBeGreaterThan(80);
  expect(missingFromSchema(calls, schema)).toEqual([]);
});
