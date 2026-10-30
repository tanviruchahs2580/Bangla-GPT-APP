import { mkdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

/**
 * Wave 2 acceptance flows, part 2: the TCH, PAR, SAD and ADM rows of the §8.3
 * flow matrix plus the heavy ANON-04 per-IP case, held as INFERRED by the
 * audit register (`.qa-work/audit/FLOWS/coverage_map.csv`).
 *
 * Harness contract as in w2-flows.spec.ts: the shipped UI against the real
 * API (mock provider, seeded accounts). No HTTP mocking except ANON-04's
 * induced 429, which replays the limiter's own captured response for the UI
 * half (named in that test).
 *
 * Deliberate limits, stated where they bite:
 *  * TCH-05 -- JOBS_BACKEND=inline completes a queued job before the first
 *    poll can observe it, so the Queued/Generating/Validating walk cannot be
 *    sampled on this harness; test_ai_jobs.py pins the state machine. What is
 *    driven here is the queue UI, the Ready outcome and the saved document.
 *    The flow's "job-ready notification" does not exist (no notification is
 *    written when an AiJob completes); recorded in the wave-2 report.
 *  * TCH-07 -- the document library has no search field (kind filters only);
 *    "search" is N/A with that evidence.
 *  * PAR-01 -- /parents/link/invite carries no rate-limit rule in
 *    initialize/middleware_stack.py, so "with rate limiting" is N/A for that
 *    route; the UI path and the single-use rule are driven.
 *  * SAD-01 -- equality with SQL computed by a different engine is the DB
 *    audit's; here the dashboard is compared with the app's own per-row data
 *    (rosters, teacher and class lists) recomputed in the spec.
 */

const PASSWORD = "E2ePass!2345";
const STUDENT = "student1@e2e.test";
const TEACHER = "teacher1@e2e.test";
const TEACHER2 = "teacher2@e2e.test";
const PARENT = "parent1@e2e.test";
const ADMIN = "admin1@e2e.test";
const SCHOOL_ADMIN = "schooladmin1@e2e.test";

const INSUFFICIENT_EVIDENCE =
  "উত্তরটি পাঠ্যবইয়ের বিষয়বস্তুর ভিত্তিতে দেওয়া সম্ভব নয়";

/** Set by TCH-02, used by TCH-03/06/09: the imported student's account. */
let importedStudent = { email: "", code: "" };
/** Set by SAD-02, used by SAD-01: a teacher tenant-scoped to E2E School. */
let schoolTeacherToken = "";

const BENIGN_CONSOLE = [/Failed to load resource/i, /net::ERR_FAILED/];
let consoleErrors: string[] = [];

test.describe.configure({ timeout: 6 * 60_000 });

test.beforeEach(async ({ page }) => {
  consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));
});

test.afterEach(() => {
  const unexpected = consoleErrors.filter(
    (text) => !BENIGN_CONSOLE.some((pattern) => pattern.test(text)),
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

/** A real graded quiz attempt for the signed-in student. */
async function gradedQuizAttempt(page: Page, numQuestions = 3): Promise<void> {
  const me = await apiGet<{ profile_id: number }>(page, "/users/me");
  const started = await page.request.post("/api/quizzes", {
    headers: await authHeaders(page),
    data: {
      student_id: me.profile_id,
      subject: "science",
      class_level: 6,
      num_questions: numQuestions,
    },
  });
  expect(started.status(), await started.text()).toBe(200);
  const quiz = (await started.json()) as {
    attempt_id: number;
    questions: { id: string }[];
  };
  const submitted = await page.request.post(
    `/api/quizzes/${quiz.attempt_id}/submit`,
    {
      headers: await authHeaders(page),
      data: { answers: quiz.questions.map(() => 0) },
    },
  );
  expect(submitted.status(), await submitted.text()).toBe(200);
}

/** The class-6 science chapter names the corpus really has. */
async function classSixScienceChapters(page: Page): Promise<string[]> {
  const rows = await apiGet<{ chapter: string }[]>(
    page,
    "/learn/subjects/science/chapters?class_level=6",
  );
  return rows.map((row) => row.chapter);
}

/** The W2 classroom TCH-02 creates. */
async function w2Room(
  page: Page,
): Promise<{ id: number; class_level: number; section: string }> {
  const rooms = await apiGet<
    { id: number; class_level: number; section: string }[]
  >(page, "/teacher/classrooms");
  const room = rooms.find((r) => r.class_level === 6 && r.section === "W2");
  expect(room, "TCH-02's classroom is missing").toBeTruthy();
  return room!;
}

async function ask(page: Page, question: string) {
  const box = page.getByRole("textbox", {
    name: /পাঠ্যবই থেকে যেকোনো প্রশ্ন লিখুন|Ask anything from your textbook/,
  });
  await box.fill(question);
  await page.getByRole("button", { name: /পাঠান|Send/ }).first().click();
  return page.locator(".bubble.assistant").last();
}

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

/* ------------------------------------------------------------------- TCH */

test("TCH-01 teacher dashboard numbers equal the API and the workload metric is recomputed from real rows", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, TEACHER);
  await expect(page).toHaveURL(/\/teacher$/);

  // The dashboard's three stats are the API's numbers, read in the same page.
  const rooms = await apiGet<{ id: number; student_count: number }[]>(
    page,
    "/teacher/classrooms",
  );
  const papers = await apiGet<{ status: string }[]>(page, "/teacher/qpapers");
  const expectedStudents = rooms.reduce((sum, r) => sum + r.student_count, 0);
  const expectedDrafts = papers.filter((p) => p.status !== "final").length;
  const statCells = page.locator(".stat-row").first().locator(".stat-value");
  await expect(statCells.first()).toBeVisible({ timeout: 30_000 });
  const nums = (await statCells.allTextContents()).map((n) => n.trim());
  expect(nums[0]).toBe(String(expectedStudents));
  expect(nums[1]).toBe(String(rooms.length));
  expect(nums[2]).toBe(String(expectedDrafts));

  // Workload: the tile carries the documented methodology and the API's
  // total, and the total is the real row counts times the documented
  // constants -- recomputed here from the constants block in the API source.
  const constantsSource = readFileSync(
    new URL(
      "../../api/src/bangla_gpt_api/routers/workspace.py",
      import.meta.url,
    ),
    "utf8",
  );
  const constants: Record<string, number> = {};
  const block = /_MINUTES_SAVED_PER_ARTIFACT[^=]*=\s*{([^}]*)}/.exec(
    constantsSource,
  )?.[1];
  expect(block, "the workload constants block was not found").toBeTruthy();
  for (const match of block!.matchAll(/"([a-z_]+)":\s*(\d+)/g)) {
    constants[match[1]] = Number(match[2]);
  }
  expect(Object.keys(constants).length).toBeGreaterThan(0);

  const workload = await apiGet<{
    counts: Record<string, number>;
    minutes_saved: Record<string, number>;
    total_minutes_saved: number;
    estimate: boolean;
    methodology: string;
  }>(page, "/teacher/workload");
  for (const [kind, minutes] of Object.entries(workload.minutes_saved)) {
    expect(minutes).toBe(constants[kind] * workload.counts[kind]);
  }
  expect(workload.total_minutes_saved).toBe(
    Object.values(workload.minutes_saved).reduce((sum, n) => sum + n, 0),
  );
  expect(workload.estimate).toBe(true);

  const tile = page.locator(".stat-row[title]").first();
  await expect(tile.locator(".num")).toHaveText(
    String(workload.total_minutes_saved),
  );
  expect((await tile.getAttribute("title")) ?? "").toContain(
    "planning constants",
  );

  // A real generator run moves the metric by exactly one documented unit.
  await open(page, "/teacher/create?kind=worksheet");
  const generate = page.getByRole("button", { name: "Generate now" });
  await expect(generate).toBeVisible({ timeout: 30_000 });
  // Every evidence-backed generator requires a chapter (WorksheetIn.chapter
  // is min_length=1), so the form gates the button on it instead of letting
  // an unanswerable request leave the page.
  await expect(generate).toBeDisabled();
  await page
    .getByLabel("Chapter (required)")
    .fill((await classSixScienceChapters(page))[0]);
  await expect(generate).toBeEnabled();
  const before = workload.counts.worksheet;
  await generate.click();
  // A fresh worksheet carries tiers, not a flat `questions` array, so the
  // payload renders as the JSON view -- same acceptance as TCH-07's stored
  // document (`.gen-json, ol.gen-questions`); the raw `ol` only exists for
  // payloads shaped `{questions: [...]}`.
  const generated = page.locator(".gen-json, ol.gen-questions").first();
  await expect(generated).toBeVisible({ timeout: 60_000 });
  const after = await apiGet<{
    counts: Record<string, number>;
    total_minutes_saved: number;
  }>(page, "/teacher/workload");
  expect(after.counts.worksheet).toBe(before + 1);
  expect(after.total_minutes_saved).toBe(
    workload.total_minutes_saved + constants.worksheet,
  );
});

test("TCH-02 classroom create, roster, and the CSV import matrix", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, TEACHER);

  // CRUD: create through the shipped form, read back through the list.
  // (The API has no update/delete for classrooms -- list + create only.)
  await open(page, "/teacher/classes");
  await page.locator("#ncls").selectOption("6");
  await page.locator("#nsec").fill("W2");
  await page.getByRole("button", { name: "New class" }).click();
  await expect
    .poll(
      async () => {
        const rows = await apiGet<
          { class_level: number; section: string }[]
        >(page, "/teacher/classrooms");
        return rows.some((r) => r.class_level === 6 && r.section === "W2");
      },
      { message: "the created classroom never appeared", timeout: 30_000 },
    )
    .toBe(true);
  const room = await w2Room(page);
  // A duplicate section is refused by the same unique constraint.
  const duplicate = await page.request.post("/api/teacher/classrooms", {
    headers: await authHeaders(page),
    data: { class_level: 6, section: "W2" },
  });
  expect(duplicate.status(), await duplicate.text()).toBe(409);

  // Valid file with Bangla names: UI import, per-row invite codes.
  await open(page, "/teacher/classes");
  await page
    .locator("textarea.mono-block")
    .fill(
      "name,email\nরহিম উদ্দিন,w2-rahim@e2e.test\nকরিম মিয়া,w2-karim@e2e.test\n",
    );
  await page.getByRole("button", { name: "Import" }).click();
  const status = page.locator('[role="status"]').filter({ hasText: "Created" });
  await expect(status).toBeVisible({ timeout: 60_000 });
  await expect(status).toContainText("Created: 2");
  await expect(status).toContainText("Failed: 0");
  // The plaintext invite code is shown exactly once -- capture it for TCH-03
  // (the imported account's initial password, must_change_password=true).
  const rahimRow = status
    .locator("table.data tbody tr", { hasText: "রহিম উদ্দিন" })
    .first();
  importedStudent = {
    email: "w2-rahim@e2e.test",
    code: ((await rahimRow.locator("code").textContent()) ?? "").trim(),
  };
  expect(importedStudent.code.length).toBeGreaterThan(7);
  const roster = await apiGet<{ name: string; email: string }[]>(
    page,
    `/teacher/classrooms/${room.id}/roster`,
  );
  expect(roster.map((r) => r.name)).toEqual(
    expect.arrayContaining(["রহিম উদ্দিন", "করিম মিয়া"]),
  );

  // The rest of the matrix through the app's own import endpoint: a UTF-8 BOM
  // header, duplicates (case-insensitive), invalid rows, a formula string and
  // an oversized file each answer the documented per-row status.
  const upload = async (csvText: string) =>
    page.request.post(`/api/teacher/classrooms/${room.id}/import`, {
      headers: await authHeaders(page),
      data: { csv_text: csvText },
    });
  const bom = await upload("\uFEFFname,email\nবোমা ছাত্র,bom@e2e.test\n");
  expect(bom.status(), await bom.text()).toBe(200);
  expect(((await bom.json()) as { created: number }).created).toBe(1);

  const dupes = await upload(
    "name,email\nSame,w2-rahim@e2e.test\nOther,W2-RAHIM@e2e.test\n",
  );
  const dupeBody = (await dupes.json()) as {
    created: number;
    failed: number;
    rows: { status: string }[];
  };
  expect(dupeBody.created).toBe(0);
  expect(dupeBody.failed).toBe(2);
  expect(new Set(dupeBody.rows.map((r) => r.status))).toEqual(
    new Set(["duplicate_email"]),
  );

  const invalid = await upload(
    "name,email\nNo Email,\nBad Domain,name@localhost\n",
  );
  const invalidBody = (await invalid.json()) as { rows: { status: string }[] };
  expect(new Set(invalidBody.rows.map((r) => r.status))).toEqual(
    new Set(["invalid"]),
  );

  const formula = await upload(
    "name,email\n=cmd|' /C calc'!A0,w2-formula@e2e.test\n",
  );
  const formulaBody = (await formula.json()) as {
    created: number;
    rows: { name: string; status: string }[];
  };
  expect(formulaBody.created).toBe(1);
  expect(formulaBody.rows[0].name).toBe("=cmd|' /C calc'!A0");
  const formulaRoster = await apiGet<{ name: string }[]>(
    page,
    `/teacher/classrooms/${room.id}/roster`,
  );
  // Stored and rendered as data: the formula string is a plain name, never
  // evaluated (the roster table renders it as text; asserted again below).
  expect(formulaRoster.map((r) => r.name)).toContain("=cmd|' /C calc'!A0");

  const oversized = await upload(
    ["name,email"]
      .concat(
        Array.from({ length: 201 }, (_, i) => `Row ${i},w2-bulk-${i}@e2e.test`),
      )
      .join("\n"),
  );
  expect(oversized.status(), "an oversized import must be refused").toBe(422);

  // The UI shows the imported Bangla student and the formula name as text.
  await open(page, "/teacher/classes");
  await expect(
    page.locator("table.data tbody tr", { hasText: "রহিম উদ্দিন" }),
  ).toHaveCount(1, { timeout: 30_000 });
  await expect(
    page.locator("table.data tbody tr", { hasText: "=cmd|' /C calc'!A0" }),
  ).toHaveCount(1);
});

test("TCH-03 assign a take-home quiz; the student sees it with the correct deadline and can start it", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, TEACHER);
  const room = await w2Room(page);
  expect(
    importedStudent.code,
    "TCH-02 did not capture the invite code",
  ).not.toBe("");
  const chapter = (await classSixScienceChapters(page))[0];

  // A due date two days out at 10:30 local; the form posts the instant.
  const due = new Date(Date.now() + 2 * 86_400_000);
  due.setHours(10, 30, 0, 0);
  const dueLocal = `${due.getFullYear()}-${String(due.getMonth() + 1).padStart(2, "0")}-${String(
    due.getDate(),
  ).padStart(2, "0")}T10:30`;

  await open(page, "/teacher/assessments?tab=assignments");
  const rosterRow = page
    .locator("table.data tbody tr", { hasText: "রহিম উদ্দিন" })
    .first();
  await expect(rosterRow).toBeVisible({ timeout: 30_000 });
  await rosterRow.locator('input[type="checkbox"]').check();
  await page.locator("#bachap").fill(chapter);
  await page.locator("#basubj").selectOption("science");
  await page.locator("#bacount").fill("3");
  await page.locator("#badue").fill(dueLocal);
  const bulkForm = page.locator("form").filter({ has: page.locator("#bachap") });
  await bulkForm.getByRole("button", { name: /Assign/ }).click();
  // The outcome line lives on the bulk-assign card next to the form, not
  // inside it; it reports the created attempts as "N selected".
  const bulkCard = page
    .locator("section.card")
    .filter({ has: page.locator("#bachap") });
  await expect(bulkCard.locator("p.muted").first()).toContainText("selected", {
    timeout: 30_000,
  });

  // Per-student quiz: the roster row action starts an open attempt for them.
  await rosterRow.getByRole("button", { name: "Assign quiz" }).click();
  const assignForm = page.locator("form").filter({ has: page.locator("#asubj") });
  await assignForm.locator("#asubj").selectOption("science");
  await assignForm.getByRole("button", { name: "Assign quiz" }).click();
  await expect(assignForm.locator('[role="status"]')).toContainText("#", {
    timeout: 30_000,
  });

  // Server-side truth: one assignment for this student, with a progress row.
  const assignments = await apiGet<
    {
      id: number;
      chapter: string;
      due_at: string;
      attempts: { student_id: number }[];
    }[]
  >(page, "/teacher/assignments");
  const created = assignments.find((a) => a.chapter === chapter);
  expect(created, "the assignment did not reach /teacher/assignments").toBeTruthy();
  expect(created!.attempts.length).toBe(1);
  const progress = await apiGet<{ student_id: number; done: boolean }[]>(
    page,
    `/teacher/assignments/${created!.id}/progress`,
  );
  expect(progress[0].done).toBe(false);

  // Deadlines and time zone: the instant the form meant (a local wall clock)
  // round-trips exactly through the naive-UTC API.
  const stored = new Date(`${created!.due_at.replace(/Z$/, "")}Z`);
  expect(stored.toISOString()).toBe(due.toISOString());
  void room;
  await signOut(page);

  // The assigned student signs in with the one-time invite code and is forced
  // to set a personal password (must_change_password) before the session
  // lands: the app keeps the /login route and renders the change form in
  // place (forceChangeTitle), so this sign-in does not leave /login.
  await open(page, "/login");
  await page.locator("#email").fill(importedStudent.email);
  await page.locator("#password").fill(importedStudent.code);
  await page.locator('form button[type="submit"]').click();
  await expect(
    page.locator("h2", {
      hasText: /Change your password|পাসওয়ার্ড পরিবর্তন করুন/,
    }),
  ).toBeVisible({ timeout: 30_000 });
  await page.locator("#new-password").fill(PASSWORD);
  await page.locator("#confirm-password").fill(PASSWORD);
  await page
    .getByRole("button", { name: /Change password and continue|পাসওয়ার্ড/ })
    .click();
  await expect(page).toHaveURL(/\/student$/, { timeout: 30_000 });

  await open(page, "/student/quiz");
  await page.locator('[role="tab"]', { hasText: /assigned/i }).click();
  const card = page
    .locator("section.card")
    .filter({ hasText: chapter })
    .first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  const dueText = (await card.textContent()) ?? "";
  expect(dueText).toMatch(/Due|শেষ তারিখ/);
  const mine = await apiGet<{ chapter: string; due_at: string }[]>(
    page,
    "/assignments/mine",
  );
  const mineRow = mine.find((a) => a.chapter === chapter);
  expect(mineRow, "the student's own assignment feed is empty").toBeTruthy();
  // The student reads the same instant, rendered in their own zone.
  const expected = await page.evaluate(
    (iso) => new Date(`${iso.replace(/Z$/, "")}Z`).toLocaleString(),
    mineRow!.due_at,
  );
  expect(dueText).toContain(expected);

  // "Students see them" also means the work opens: the questions load.
  await card.getByRole("button", { name: /Start quiz|শুরু/ }).click();
  await expect(page.locator(".quiz-q-title").first()).toBeVisible({
    timeout: 60_000,
  });
});

test("TCH-04 question paper: generate, edit, review, finalize and download the PDFs", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, TEACHER);
  const chapter = (await classSixScienceChapters(page))[0];

  await open(page, "/teacher/create?kind=question_paper");
  await page.locator("#qpexam").fill("W2 Half Yearly");
  await page.locator("#qplvl").selectOption("6");
  await page.locator("#qpsubj").selectOption("science");
  await page.locator("#qpchapters").fill(chapter);
  await page.getByRole("button", { name: "Generate draft" }).click();
  const panel = page.locator(".qp-review-panel");
  await expect(panel).toBeVisible({ timeout: 60_000 });
  await expect(panel.locator(".qp-step").first()).toBeVisible();
  await expect(panel.locator(".qp-validation")).toBeVisible();

  // Edit question 1: type replacement text, then accept that question with the
  // edit -- the review decision carries the new text to the API.
  const questions = panel.locator(".qp-question-row");
  const total = await questions.count();
  expect(total).toBeGreaterThan(0);
  const edited = `সম্পাদিত প্রশ্ন ${total}`;
  await questions.first().getByRole("textbox").fill(edited);
  await questions.first().getByRole("button", { name: "Accept all" }).click();
  await expect(questions.first()).toContainText(edited, { timeout: 30_000 });

  // Accept the rest, then finalize (the gate opens only when all are reviewed).
  await panel.getByRole("button", { name: "Accept all" }).last().click();
  const finalize = panel.getByRole("button", { name: "Finalize" });
  await expect(finalize).toBeEnabled({ timeout: 30_000 });
  await finalize.click();
  // The panel's own copy for the final state is the British "Finalised"
  // (qpFinalized) while the action button above reads "Finalize"; assert the
  // state change both ways -- the badge appears and the gate controls go.
  await expect(panel.getByText("Finalised").first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(panel.getByRole("button", { name: "Finalize" })).toHaveCount(0);

  // Both downloads are real PDFs, saved as evidence for the page-render check.
  const evidenceDir = new URL(
    "../../../.qa-work/evidence/E-W2-FLOWS-2/",
    import.meta.url,
  );
  mkdirSync(evidenceDir, { recursive: true });
  const paperPath = fileURLToPath(new URL("tch04-paper.pdf", evidenceDir));
  const answerPath = fileURLToPath(new URL("tch04-answer.pdf", evidenceDir));
  const paperDownload = page.waitForEvent("download");
  await panel.getByRole("button", { name: "PDF", exact: true }).click();
  await (await paperDownload).saveAs(paperPath);
  const answerDownload = page.waitForEvent("download");
  await panel.getByRole("button", { name: "PDF+" }).click();
  await (await answerDownload).saveAs(answerPath);

  const paper = readFileSync(paperPath);
  const answer = readFileSync(answerPath);
  expect(paper.subarray(0, 5).toString()).toBe("%PDF-");
  expect(answer.subarray(0, 5).toString()).toBe("%PDF-");
  expect(paper.length).toBeGreaterThan(1000);
  expect(answer.length).toBeGreaterThan(paper.length / 2);

  // The reviewed paper really kept the edited text (server round-trip).
  const papers = await apiGet<
    { id: number; status: string; questions: { text: string }[] }[]
  >(page, "/teacher/qpapers");
  const final = papers.find((q) => q.status === "final");
  expect(final, "no finalized paper is stored").toBeTruthy();
  expect(final!.questions.map((q) => q.text)).toContain(edited);
});

test("TCH-05 create hub: synchronous generation, the queued job outcome, and the saved library", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, TEACHER);
  const chapter = (await classSixScienceChapters(page))[0];

  await open(page, "/teacher/create?kind=homework");
  await page.getByLabel("Chapter (required)").fill(chapter);
  await page.getByRole("button", { name: "Generate now" }).click();
  // Homework payloads carry `items`, so the result renders as the JSON view
  // (the stored copy is opened again at the end of this test).
  const generated = page.locator(".gen-json, ol.gen-questions").first();
  await expect(generated).toBeVisible({ timeout: 60_000 });

  // Queued job: the UI posts it and polls; the row must reach Ready and link
  // the stored document. (JOBS_BACKEND=inline completes the job before the
  // first poll can see queued/generating/validating; the API state machine is
  // pinned by apps/api/tests/test_ai_jobs.py.)
  const jobResponse = page.waitForResponse(
    (res) =>
      res.url().includes("/teacher/jobs") && res.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Run in background" }).click();
  const job = (await (await jobResponse).json()) as { id: string };
  expect(job.id).toBeTruthy();
  await expect
    .poll(
      async () =>
        (await apiGet<{ status: string }>(page, `/teacher/jobs/${job.id}`))
          .status,
      { message: "the queued job never reached ready", timeout: 60_000 },
    )
    .toBe("ready");
  const jobRow = await apiGet<{
    error: string | null;
    result: { document_id?: number } | null;
  }>(page, `/teacher/jobs/${job.id}`);
  expect(jobRow.error).toBeNull();
  expect(jobRow.result?.document_id).toBeGreaterThan(0);
  await expect(
    page.locator("table.data tbody tr", { hasText: "Ready" }).first(),
  ).toBeVisible({ timeout: 30_000 });

  // The generated document is in the library, opens with its payload, and
  // survives a reload (server-side row, not component state).
  const docs = await apiGet<{ id: number; kind: string }[]>(
    page,
    "/teacher/documents",
  );
  expect(docs.some((d) => d.id === jobRow.result!.document_id)).toBe(true);
  await open(page, "/teacher/create?kind=worksheet");
  const docRow = page
    .locator(".gen-doc-row")
    .filter({ hasText: "Homework" })
    .first();
  await expect(docRow).toBeVisible({ timeout: 30_000 });
  await docRow.locator(".gen-doc-open").click();
  await expect(page.locator(".gen-json, ol.gen-questions").first()).toBeVisible();
});

test("TCH-06 lesson plans persist and stay editable; short tests and support plans work", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, TEACHER);
  const chapter = (await classSixScienceChapters(page))[0];

  // Lesson plan: generated in the UI, all eight sections editable, and the
  // generated plan persisted as a library document.
  await open(page, "/teacher/create?kind=lesson_plan");
  await page.locator("#lpchap").fill(chapter);
  await page.locator("#lpsubj").selectOption("science");
  await page.getByRole("button", { name: "Generate", exact: true }).click();
  const sections = page.locator('[id^="lpsec-"]');
  await expect(sections).toHaveCount(8, { timeout: 60_000 });
  const first = sections.first();
  const original = await first.inputValue();
  expect(original.length).toBeGreaterThan(0);
  await first.fill(`${original} (revised)`);
  await expect(first).toHaveValue(`${original} (revised)`);
  const plans = await apiGet<{ id: number; kind: string; chapter: string }[]>(
    page,
    "/teacher/documents?kind=lesson_plan&limit=100",
  );
  expect(
    plans.find((p) => p.chapter === chapter),
    "the lesson plan was not persisted",
  ).toBeTruthy();

  // Short test: assigned to the first classroom in the selector from the UI.
  await open(page, "/teacher/create?kind=short_test");
  await page.locator("#stchap").fill(chapter);
  const roomSelect = page.locator("#strom");
  const roomValue = await roomSelect
    .locator("option")
    .first()
    .getAttribute("value");
  await roomSelect.selectOption(roomValue!);
  await page.getByRole("button", { name: "Assign", exact: true }).click();
  await expect(page.locator("p.muted", { hasText: "Assigned to" })).toBeVisible({
    timeout: 60_000,
  });
  const shortTests = await apiGet<{ chapter: string; attempts: unknown[] }[]>(
    page,
    "/teacher/shorttests",
  );
  const shortTest = shortTests.find((s) => s.chapter === chapter);
  expect(shortTest, "the short test was not stored").toBeTruthy();
  expect(shortTest!.attempts.length).toBeGreaterThan(0);

  // Support plan for a roster student, created from the student detail card.
  await open(page, "/teacher/classes");
  const row = page
    .locator("table.data tbody tr", { hasText: "রহিম উদ্দিন" })
    .first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  // The plan ranks the student's three weakest concepts, so the API refuses
  // a student with no graded attempt (422 no_graded_data, assessment.py).
  // Seed one through the student's own quiz hub before opening the plan;
  // id and email come from the roster rather than TCH-02's module state, so
  // an earlier failure cannot leave this test reading empty strings.
  const room = await w2Room(page);
  const roster = await apiGet<
    { student_id: number; name: string; email: string | null }[]
  >(page, `/teacher/classrooms/${room.id}/roster`);
  const rahim = roster.find((s) => s.name === "রহিম উদ্দিন");
  expect(rahim, "TCH-02's imported student is missing").toBeTruthy();
  expect(
    rahim!.email,
    "the roster has no email for the imported student",
  ).toBeTruthy();
  const rahimLogin = await page.request.post("/api/auth/login", {
    data: { email: rahim!.email, password: PASSWORD },
  });
  expect(rahimLogin.status(), await rahimLogin.text()).toBe(200);
  const rahimHeaders = {
    Authorization: `Bearer ${((await rahimLogin.json()) as { access_token: string }).access_token}`,
    "Content-Type": "application/json",
  };
  const rahimQuiz = await page.request.post("/api/quizzes", {
    headers: rahimHeaders,
    data: {
      student_id: rahim!.student_id,
      class_level: 6,
      subject: "science",
      num_questions: 3,
    },
  });
  expect(rahimQuiz.status(), await rahimQuiz.text()).toBe(200);
  const rahimAttempt = (await rahimQuiz.json()) as {
    attempt_id: number;
    questions: unknown[];
  };
  const rahimSubmit = await page.request.post(
    `/api/quizzes/${rahimAttempt.attempt_id}/submit`,
    {
      headers: rahimHeaders,
      data: { answers: rahimAttempt.questions.map(() => 0) },
    },
  );
  expect(rahimSubmit.status(), await rahimSubmit.text()).toBe(200);

  await row.getByRole("button", { name: "Open" }).click();
  await expect(page.getByText("Student details")).toBeVisible({ timeout: 30_000 });
  const plansBefore = await apiGet<unknown[]>(page, "/teacher/support-plans");
  await page.getByRole("button", { name: "Create support plan" }).click();
  await expect
    .poll(
      async () => (await apiGet<unknown[]>(page, "/teacher/support-plans")).length,
      { message: "the support plan was not stored", timeout: 30_000 },
    )
    .toBe(plansBefore.length + 1);
  await expect(page.getByText("Support plan").first()).toBeVisible();
});

test("TCH-07 document library: list, open, filter, persist across sessions and delete", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, TEACHER);
  await open(page, "/teacher/create?kind=worksheet");

  const before = await apiGet<{ id: number; kind: string; title: string }[]>(
    page,
    "/teacher/documents",
  );
  expect(before.length).toBeGreaterThan(0);
  const target = before.find((d) => d.kind === "worksheet") ?? before[0];

  // List + open: the row renders and the payload opens in place.
  const row = page
    .locator(".gen-doc-row")
    .filter({ hasText: target.title })
    .first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.locator(".gen-doc-open").click();
  await expect(page.locator(".gen-json, ol.gen-questions").first()).toBeVisible();

  // Kind filter (the library has no free-text search; kind chips only).
  await page.getByRole("button", { name: "Lesson plan", exact: true }).click();
  await expect
    .poll(
      async () =>
        (
          await apiGet<{ kind: string }[]>(
            page,
            "/teacher/documents?kind=lesson_plan&limit=100",
          )
        ).every((d) => d.kind === "lesson_plan"),
      { timeout: 30_000 },
    )
    .toBe(true);
  await page.getByRole("button", { name: "All", exact: true }).click();

  // Persists across sessions: sign out and back in, the row is still listed.
  await signOut(page);
  await signIn(page, TEACHER);
  await open(page, "/teacher/create?kind=worksheet");
  const after = await apiGet<{ id: number }[]>(page, "/teacher/documents");
  expect(after.map((d) => d.id)).toContain(target.id);
  await expect(
    page.locator(".gen-doc-row").filter({ hasText: target.title }).first(),
  ).toBeVisible({ timeout: 30_000 });

  // Delete takes the two-step confirm and removes the row for real.
  const delRow = page
    .locator(".gen-doc-row")
    .filter({ hasText: target.title })
    .first();
  await delRow.getByRole("button", { name: "Delete", exact: true }).click();
  await delRow.getByRole("button", { name: "Yes, delete" }).click();
  await expect
    .poll(
      async () =>
        (await apiGet<{ id: number }[]>(page, "/teacher/documents")).some(
          (d) => d.id === target.id,
        ),
      { message: "the deleted document is still stored", timeout: 30_000 },
    )
    .toBe(false);
  await expect(
    page.locator(".gen-doc-row").filter({ hasText: target.title }),
  ).toHaveCount(0);
});

test("TCH-08 weak matrix and coverage equal independently queried values", async ({
  page,
}) => {
  await pin(page, "en");

  // The matrix is scoped to the teacher's own classrooms, so the row has to
  // come from a student in one of them: student1 is enrolled in none of
  // teacher1's rooms (measured: the page rendered its "no graded quizzes"
  // empty state). রহিম was imported into the W2 room by TCH-02; give him a
  // graded attempt through his own account, then read everything back as the
  // teacher. The account comes from the roster, not TCH-02's module state.
  await signIn(page, TEACHER);
  const room = await w2Room(page);
  const roster = await apiGet<
    { student_id: number; name: string; email: string | null }[]
  >(page, `/teacher/classrooms/${room.id}/roster`);
  const target = roster.find((s) => s.name === "রহিম উদ্দিন");
  expect(target, "TCH-02's imported student is missing").toBeTruthy();
  expect(
    target!.email,
    "the roster has no email for the imported student",
  ).toBeTruthy();
  const rahimLogin = await page.request.post("/api/auth/login", {
    data: { email: target!.email, password: PASSWORD },
  });
  expect(rahimLogin.status(), await rahimLogin.text()).toBe(200);
  const rahimHeaders = {
    Authorization: `Bearer ${((await rahimLogin.json()) as { access_token: string }).access_token}`,
    "Content-Type": "application/json",
  };
  const rahimQuiz = await page.request.post("/api/quizzes", {
    headers: rahimHeaders,
    data: {
      student_id: target!.student_id,
      class_level: 6,
      subject: "science",
      num_questions: 3,
    },
  });
  expect(rahimQuiz.status(), await rahimQuiz.text()).toBe(200);
  const rahimAttempt = (await rahimQuiz.json()) as {
    attempt_id: number;
    questions: unknown[];
  };
  const rahimSubmit = await page.request.post(
    `/api/quizzes/${rahimAttempt.attempt_id}/submit`,
    {
      headers: rahimHeaders,
      data: { answers: rahimAttempt.questions.map(() => 0) },
    },
  );
  expect(rahimSubmit.status(), await rahimSubmit.text()).toBe(200);
  const progress = await apiGet<{
    by_chapter: {
      chapter: string;
      asked: number;
      correct: number;
      accuracy: number;
    }[];
  }>(page, `/students/${target!.student_id}/progress`);
  expect(progress.by_chapter.length).toBeGreaterThan(0);

  await open(page, "/teacher/analytics");
  const matrixCard = page
    .locator("section.card")
    .filter({ hasText: "Weakness map" })
    .first();
  await expect(matrixCard).toBeVisible({ timeout: 30_000 });
  const matrix = await apiGet<{
    concepts: string[];
    students: {
      student_id: number;
      cells: Record<
        string,
        { asked: number; correct: number; accuracy: number | null }
      >;
    }[];
  }>(page, "/teacher/weak-matrix?class_level=6");
  expect(matrix.students.length).toBeGreaterThan(0);
  expect(
    matrix.concepts.length,
    "the matrix has no concept column to compare",
  ).toBeGreaterThan(0);

  // The rendered grid cell equals the API's accuracy for the same
  // student/concept pair -- and for রহিম, the API's numbers equal the
  // per-chapter accuracy queried independently from his own progress rows.
  const table = matrixCard.locator("table.data");
  await expect(table).toBeVisible();
  const bodyRows = await table.locator("tbody tr").all();
  const labels = await Promise.all(
    bodyRows.map(async (bodyRow) =>
      ((await bodyRow.locator("th").first().textContent()) ?? "").trim(),
    ),
  );
  for (const concept of matrix.concepts.slice(0, 4)) {
    const index = labels.indexOf(concept);
    expect(
      index,
      `no rendered row for concept ${concept}`,
    ).toBeGreaterThanOrEqual(0);
    const cells = bodyRows[index].locator("td");
    for (let i = 0; i < matrix.students.length; i += 1) {
      const student = matrix.students[i];
      const expected = student.cells[concept];
      const rendered = ((await cells.nth(i).textContent()) ?? "").trim();
      expect(rendered).toBe(
        expected && expected.accuracy !== null
          ? `${Math.round(expected.accuracy)}%`
          : "·",
      );
      if (student.student_id === target!.student_id) {
        const source = progress.by_chapter.find((c) => c.chapter === concept);
        if (source) {
          expect(expected?.asked).toBe(source.asked);
          expect(expected?.correct).toBe(source.correct);
        }
      }
    }
  }

  // Curriculum coverage: every rendered badge is one of the API's statuses.
  const coverage = await apiGet<{
    subjects: string[];
    cells: { classroom_id: number; subject: string; status: string }[];
  }>(page, "/teacher/curriculum-coverage");
  expect(coverage.cells.length).toBeGreaterThan(0);
  const coverageCard = page
    .locator("section.card")
    .filter({ hasText: "Curriculum coverage" })
    .first();
  const coverageTable = coverageCard.locator("table.data");
  await expect(coverageTable).toBeVisible({ timeout: 30_000 });
  const statusLabel: Record<string, string> = {
    mastered: "Mastered",
    practiced: "Practiced",
    taught: "Taught",
    // The app's copy for the uncovered status is "Not started" (covUncovered).
    uncovered: "Not started",
  };
  const statuses = new Set(coverage.cells.map((c) => statusLabel[c.status]));
  const renderedBadges = await coverageTable.locator(".badge").allTextContents();
  expect(renderedBadges.length).toBeGreaterThan(0);
  for (const badge of renderedBadges) {
    expect(statuses.has(badge.trim())).toBe(true);
  }

  // Class analytics (the Chapters stat on /teacher/classes) equals the
  // analytics endpoint for the same grade.
  const analytics = await apiGet<{ chapters: unknown[] }>(
    page,
    "/teacher/classes/6/analytics",
  );
  await open(page, "/teacher/classes");
  const statCells = page.locator(".stat-row").first().locator(".stat-value");
  await expect(statCells.first()).toBeVisible({ timeout: 30_000 });
  const nums = (await statCells.allTextContents()).map((n) => n.trim());
  expect(nums[1]).toBe(String(analytics.chapters.length));
});

test("TCH-09 student detail matches the source; another school's classroom and another teacher's paper are denied", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, TEACHER);

  // Student detail view: the roster row opens the student's real numbers.
  await open(page, "/teacher/classes");
  const row = page
    .locator("table.data tbody tr", { hasText: "রহিম উদ্দিন" })
    .first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  const studentId = Number(
    (await row.locator("td").first().textContent())?.trim(),
  );
  expect(Number.isInteger(studentId)).toBe(true);
  await row.getByRole("button", { name: "Open" }).click();
  const detailCard = page
    .locator("section.card")
    .filter({ hasText: "Student details" })
    .first();
  await expect(detailCard).toBeVisible({ timeout: 30_000 });
  const detail = await apiGet<{ attempts_graded: number }>(
    page,
    `/students/${studentId}/progress`,
  );
  await expect(detailCard).toContainText(
    `Graded quizzes: ${detail.attempts_graded}`,
  );

  // Another school: a classroom outside the teacher's tenant school is 403
  // while the own room answers 200 -- scoping, not breakage.
  await signOut(page);
  await signIn(page, ADMIN);
  const schoolName = `W2 Other School ${Date.now()}`;
  await page.locator("#nschool").fill(schoolName);
  await page.getByRole("button", { name: "Create school" }).click();
  await expect(
    page.locator("table.data tbody td", { hasText: schoolName }),
  ).toBeVisible({ timeout: 30_000 });
  const other = (
    await apiGet<{ id: number; name: string }[]>(page, "/admin/schools")
  ).find((s) => s.name === schoolName);
  const otherRoom = await page.request.post(
    `/api/schools/${other!.id}/classes`,
    {
      headers: await authHeaders(page),
      data: { class_level: 6, section: "OTH" },
    },
  );
  expect(otherRoom.status(), await otherRoom.text()).toBe(201);
  const otherRoomId = ((await otherRoom.json()) as { id: number }).id;
  await signOut(page);

  await signIn(page, TEACHER);
  const ownRoom = await w2Room(page);
  const denied = await page.request.get(
    `/api/teacher/classrooms/${otherRoomId}/roster`,
    { headers: await authHeaders(page) },
  );
  // F-144: a cross-school room answers 404 classroom_not_found, the same
  // response a room id that was never issued gets -- no existence oracle.
  // A 200 would be the defect; a 403 would still confirm the room exists.
  expect(denied.status(), "another school's classroom was readable").toBe(404);
  expect(
    ((await denied.json()) as { detail: { code: string } }).detail.code,
  ).toBe("classroom_not_found");
  const allowed = await page.request.get(
    `/api/teacher/classrooms/${ownRoom.id}/roster`,
    { headers: await authHeaders(page) },
  );
  expect(allowed.status()).toBe(200);
  await signOut(page);

  // Another teacher cannot touch this teacher's question paper: the paper is
  // owner-scoped and the miss is indistinguishable from a missing row (404).
  await signIn(page, TEACHER);
  const chapter = (await classSixScienceChapters(page))[0];
  const qp = await page.request.post("/api/teacher/qpapers", {
    headers: await authHeaders(page),
    data: {
      class_level: 6,
      subject: "science",
      chapters: [chapter],
      exam_type: "W2 IDOR",
      marks: 10,
      duration_min: 10,
      difficulty: { easy: 30, medium: 50, hard: 20 },
    },
  });
  expect(qp.status(), await qp.text()).toBe(201);
  const qpId = ((await qp.json()) as { id: number }).id;
  await signOut(page);

  await signIn(page, TEACHER2);
  const foreign = await page.request.post(
    `/api/teacher/qpapers/${qpId}/review`,
    {
      headers: await authHeaders(page),
      data: { decisions: [{ ref: "x", action: "accept" }] },
    },
  );
  expect(
    foreign.status(),
    "another teacher could review a paper they do not own",
  ).toBe(404);
  expect(
    ((await foreign.json()) as { detail: { code: string } }).detail.code,
  ).toBe("qpaper_not_found");
  const foreignPdf = await page.request.get(
    `/api/teacher/qpapers/${qpId}/pdf?kind=paper`,
    { headers: await authHeaders(page) },
  );
  expect(foreignPdf.status()).toBe(404);
});

/* ------------------------------------------------------------------- PAR */

test("PAR-01 a valid invite links a child, the code is single-use, and a wrong code is refused", async ({
  page,
}) => {
  await pin(page, "en");
  // The student issues a single-use code through the profile page.
  await signIn(page, STUDENT);
  await open(page, "/student/me");
  await page.getByRole("button", { name: "Generate code" }).click();
  const code = (await page.locator(".invite-code").textContent())?.trim() ?? "";
  expect(code).toMatch(/^BGPT-[A-F0-9]{16}$/);
  await signOut(page);

  await signIn(page, PARENT);
  await page.locator("#icode").fill(code);
  await page.getByRole("button", { name: "Link", exact: true }).click();
  // The code is consumed either way; a second redirection of the same code
  // answers 409 already_linked and the first link is already in place.
  const outcome = page.locator('[role="status"], [role="alert"]').first();
  await expect(outcome).toBeVisible({ timeout: 30_000 });
  const children = await apiGet<{ name: string }[]>(
    page,
    "/parents/me/children",
  );
  expect(children.map((c) => c.name)).toContain("E2E Student");

  // Single use: the same code cannot be redeemed again. The copy names the
  // invite code specifically ("The invite code is invalid or expired.").
  await page.locator("#icode").fill(code);
  await page.getByRole("button", { name: "Link", exact: true }).click();
  await expect(page.locator('[role="alert"]').first()).toContainText(
    "The invite code is invalid or expired",
    { timeout: 30_000 },
  );

  // A wrong code gets the same refusal. Rate limiting: /parents/link/invite
  // has no rule in initialize/middleware_stack.py, so there is nothing to
  // trip; the API test suite pins the code-level contract.
  await page.locator("#icode").fill("BGPT-0000000000000000");
  await page.getByRole("button", { name: "Link", exact: true }).click();
  await expect(page.locator('[role="alert"]').first()).toContainText(
    "The invite code is invalid or expired",
    { timeout: 30_000 },
  );
});

test("PAR-02 child list, per-chapter accuracy and the activity feed match the source data", async ({
  page,
}) => {
  await pin(page, "en");
  // Real activity first: a graded attempt for student1.
  await signIn(page, STUDENT);
  await gradedQuizAttempt(page);
  await signOut(page);

  await signIn(page, PARENT);
  const children = await apiGet<{ student_id: number; name: string }[]>(
    page,
    "/parents/me/children",
  );
  const child = children.find((c) => c.name === "E2E Student");
  expect(child, "parent1 is not linked to student1").toBeTruthy();

  const progress = await apiGet<{
    avg_score_pct: number | null;
    by_chapter: {
      chapter: string;
      asked: number;
      correct: number;
      accuracy: number;
    }[];
  }>(page, `/parents/me/children/${child!.student_id}/progress`);
  const activity = await apiGet<{
    days: { date: string; questions: number; quizzes: number }[];
  }>(page, `/parents/me/children/${child!.student_id}/activity`);

  // The list row carries the same average as the source.
  await open(page, "/parent");
  const row = page.locator("table.data tbody tr", { hasText: "E2E Student" });
  await expect(row).toHaveCount(1, { timeout: 30_000 });
  await expect(row.locator("td").nth(3)).toHaveText(
    progress.avg_score_pct === null ? "—" : `${progress.avg_score_pct}%`,
  );
  await row.getByRole("button", { name: "My progress" }).click();

  // Per-chapter accuracy: every rendered row equals the API's row.
  const progressCard = page
    .locator("div.card")
    .filter({ has: page.getByRole("heading", { name: /^My progress — / }) })
    .first();
  await expect(progressCard).toBeVisible({ timeout: 30_000 });
  const byChapterTable = progressCard.locator("table.data");
  await expect(byChapterTable).toBeVisible();
  expect(progress.by_chapter.length).toBeGreaterThan(0);
  for (const chapter of progress.by_chapter) {
    const chapterRow = byChapterTable
      .locator("tbody tr", { hasText: chapter.chapter })
      .first();
    const cells = (await chapterRow.locator("td").allTextContents()).map((c) =>
      c.trim(),
    );
    expect(cells[0]).toBe(chapter.chapter);
    expect(cells[1]).toBe(String(chapter.asked));
    expect(cells[2]).toBe(String(chapter.correct));
    expect(cells[3]).toContain(`${chapter.accuracy}%`);
  }

  // Activity feed: the heatmap's per-day bucket equals the source counts.
  const heat = page.locator(".heatmap");
  await expect(heat).toBeVisible({ timeout: 30_000 });
  const cells = heat.locator(".heat-cell");
  await expect(cells).toHaveCount(activity.days.length);
  for (let i = 0; i < activity.days.length; i += 1) {
    const day = activity.days[i];
    const total = day.questions + day.quizzes;
    const bucket = total === 0 ? 0 : total <= 2 ? 1 : total <= 5 ? 2 : 3;
    await expect(cells.nth(i)).toHaveClass(new RegExp(`lvl-${bucket}(\\s|$)`));
  }
  expect((await heat.getAttribute("aria-label")) ?? "").not.toBe("");
});

/* ------------------------------------------------------------------- SAD */

test("SAD-02 a school admin manages classes and teachers inside its own school", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, SCHOOL_ADMIN);
  await expect(page).toHaveURL(/\/school$/);

  // Class: create inside the own school; the duplicate is refused.
  const overview = await apiGet<{ school_id: number; code: string }>(
    page,
    "/school/overview",
  );
  expect(overview.code).toBe("E2E-SCHOOL");
  const section = `S${Date.now() % 1000}`;
  const created = await page.request.post(
    `/api/schools/${overview.school_id}/classes`,
    { headers: await authHeaders(page), data: { class_level: 6, section } },
  );
  expect(created.status(), await created.text()).toBe(201);
  const dup = await page.request.post(
    `/api/schools/${overview.school_id}/classes`,
    { headers: await authHeaders(page), data: { class_level: 6, section } },
  );
  expect(dup.status(), "a duplicate classroom must be refused").toBe(409);
  const classes = await apiGet<{ section: string }[]>(page, "/school/classes");
  expect(classes.map((c) => c.section)).toContain(section);

  // Teacher: invite a real account into the school and see the roster grow.
  const teachersBefore = await apiGet<{ name: string }[]>(
    page,
    "/school/teachers",
  );
  const invite = await page.request.post(
    `/api/schools/${overview.school_id}/invites`,
    { headers: await authHeaders(page), data: { role: "teacher" } },
  );
  expect(invite.status(), await invite.text()).toBe(201);
  const code = ((await invite.json()) as { code: string }).code;
  const email = `w2-school-teacher-${Date.now()}@e2e.test`;
  const join = await page.request.post("/api/auth/join-school", {
    data: {
      invite_code: code,
      email,
      password: PASSWORD,
      name: "W2 School Teacher",
    },
  });
  expect(join.status(), await join.text()).toBe(201);
  schoolTeacherToken = ((await join.json()) as { access_token: string })
    .access_token;

  // The joined teacher is tenant-scoped: the school's new class is visible,
  // the other school's class (created in TCH-09) is not even listed.
  const teacherRooms = await page.request.get("/api/teacher/classrooms", {
    headers: { Authorization: `Bearer ${schoolTeacherToken}` },
  });
  expect(teacherRooms.status()).toBe(200);
  const rooms = (await teacherRooms.json()) as { section: string }[];
  expect(rooms.map((r) => r.section)).toContain(section);
  expect(rooms.map((r) => r.section)).not.toContain("OTH");

  const teachersAfter = await apiGet<{ name: string }[]>(
    page,
    "/school/teachers",
  );
  expect(teachersAfter.length).toBe(teachersBefore.length + 1);
  expect(teachersAfter.map((t) => t.name)).toContain("W2 School Teacher");
  // The dashboard renders the staff rows it was given.
  await open(page, "/school");
  const teacherSection = page
    .locator("section.card")
    .filter({ has: page.getByRole("heading", { name: "Teachers" }) })
    .first();
  await expect(teacherSection.locator("table.data tbody tr")).toHaveCount(
    teachersAfter.length,
    { timeout: 30_000 },
  );
});

test("SAD-01 the school dashboard equals the per-row data recomputed in the spec", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, SCHOOL_ADMIN);
  await open(page, "/school");

  const health = await apiGet<{
    students: number;
    teachers: number;
    classrooms: number;
    sessions_7d: number;
    strong: number;
    support: number;
    risk: number;
    ungraded: number;
    at_risk: unknown[];
  }>(page, "/school/overview");
  const students = await apiGet<{ total: number }>(
    page,
    "/school/students?limit=100&offset=0",
  );
  const teacherRows = await apiGet<{ teacher_id: number }[]>(
    page,
    "/school/teachers",
  );
  const classRows = await apiGet<{ classroom_id: number }[]>(
    page,
    "/school/classes",
  );

  // The four headline stats are the API's own numbers...
  const statGrid = page.locator(".stat-grid").first();
  const values = (await statGrid.locator(".stat-value").allTextContents()).map(
    (v) => v.trim(),
  );
  expect(values[0]).toBe(String(health.students));
  expect(values[1]).toBe(String(health.teachers));
  expect(values[2]).toBe(String(health.classrooms));
  expect(values[3]).toBe(String(health.sessions_7d));

  // ...and students/classrooms are recomputed from the rosters and room list
  // through the school-bound teacher's own endpoints (a different path to the
  // same rows).
  expect(health.students).toBe(students.total);
  expect(health.classrooms).toBe(classRows.length);
  if (schoolTeacherToken) {
    const rooms = (await (
      await page.request.get("/api/teacher/classrooms", {
        headers: { Authorization: `Bearer ${schoolTeacherToken}` },
      })
    ).json()) as { id: number }[];
    expect(health.classrooms).toBe(rooms.length);
    const rosterIds = new Set<number>();
    for (const room of rooms) {
      const roster = (await (
        await page.request.get(`/api/teacher/classrooms/${room.id}/roster`, {
          headers: { Authorization: `Bearer ${schoolTeacherToken}` },
        })
      ).json()) as { student_id: number }[];
      for (const entry of roster) rosterIds.add(entry.student_id);
    }
    expect(health.students).toBe(rosterIds.size);
  }
  // The teacher count includes the seeded school_admin account (a staff user
  // without a Teacher profile, so the staff table shows one fewer row).
  expect(health.teachers).toBe(teacherRows.length + 1);

  // The health buckets account for every student exactly once, and the
  // at-risk list holds exactly the students the bucket counted.
  expect(health.strong + health.support + health.risk + health.ungraded).toBe(
    health.students,
  );
  expect(health.at_risk.length).toBe(health.risk);
  const riskCard = page
    .locator("section.card")
    .filter({ has: page.getByRole("heading", { name: "At-risk list" }) })
    .first();
  if (health.risk === 0) {
    await expect(riskCard).toContainText("No students yet");
  } else {
    await expect(riskCard.locator("table.data tbody tr")).toHaveCount(
      health.risk,
    );
  }
});

/* ------------------------------------------------------------------- ADM */

test("ADM-01 users search, role filter, pagination, a role change with its audit row, and no self-escalation", async ({
  page,
}) => {
  await pin(page, "en");
  // A throwaway account the admin can re-role safely.
  const email = `w2-rolechange-${Date.now()}@e2e.test`;
  await open(page, "/register");
  await page.locator("#name").fill("W2 Role Change");
  await page.locator("#remail").fill(email);
  await page.locator("#rpassword").fill(PASSWORD);
  await page.locator("#consent").check();
  await page.locator('form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/student$/, { timeout: 30_000 });
  await signOut(page);

  await signIn(page, ADMIN);
  await open(page, "/admin");
  // Search: debounced, so the table settles on the single match.
  await page.locator("#q").fill(email);
  const row = page.locator("table.data tbody tr", { hasText: email });
  await expect(row).toHaveCount(1, { timeout: 30_000 });
  const userId = Number((await row.locator("td").first().textContent())?.trim());

  // Role filter: only teachers are listed. Scope the column read to the
  // users table: /admin renders several tables (schools, invites, triage)
  // whose third column is not a role, and a page-wide td:nth-child(3) sweep
  // reads them too.
  await page.locator("#q").fill("");
  await page.locator("#rfilter").selectOption("teacher");
  const usersCard = page
    .locator("div.card")
    .filter({ has: page.locator("#q") });
  await expect
    .poll(
      async () => {
        const roles = await usersCard
          .locator("table.data tbody tr td:nth-child(3)")
          .allTextContents();
        return roles.length > 0 && roles.every((r) => r.trim() === "Teacher");
      },
      { timeout: 30_000 },
    )
    .toBe(true);
  await page.locator("#rfilter").selectOption("");

  // Pagination: the range line moves with the page and comes back.
  const pager = usersCard
    .locator("p.muted")
    .filter({ has: page.getByRole("button", { name: "Next page" }) })
    .first();
  const firstRange = (await pager.textContent()) ?? "";
  const next = page.getByRole("button", { name: "Next page" });
  if (await next.isEnabled()) {
    await next.click();
    await expect
      .poll(async () => (await pager.textContent()) ?? "", { timeout: 20_000 })
      .not.toBe(firstRange);
    await page.getByRole("button", { name: "Previous page" }).click();
    await expect
      .poll(async () => (await pager.textContent()) ?? "", { timeout: 20_000 })
      .toBe(firstRange);
  }

  // Role change through the row select: student -> teacher, with an audit row.
  await page.locator("#q").fill(email);
  const targetRow = page.locator("table.data tbody tr", { hasText: email });
  await expect(targetRow).toHaveCount(1, { timeout: 30_000 });
  await targetRow
    .getByRole("combobox", { name: `${email} Role` })
    .selectOption("teacher");
  await expect
    .poll(
      async () =>
        (
          await apiGet<{ items: { role: string }[] }>(
            page,
            `/admin/users?q=${encodeURIComponent(email)}`,
          )
        ).items[0]?.role,
      { timeout: 30_000 },
    )
    .toBe("teacher");
  const audit = await apiGet<{
    rows: { action: string; target: string; detail: Record<string, unknown> }[];
  }>(page, "/admin/audit?action=role_change&limit=20");
  const changeRow = audit.rows.find(
    (r) => r.target === `user:${userId}` && r.detail.to === "teacher",
  );
  expect(changeRow, "the role change left no audit row").toBeTruthy();
  expect(changeRow!.detail.from).toBe("student");

  // Self-escalation: a student session cannot call the role endpoint...
  const studentLogin = await page.request.post("/api/auth/login", {
    data: { email: STUDENT, password: PASSWORD },
  });
  const studentToken = ((await studentLogin.json()) as { access_token: string })
    .access_token;
  const escalated = await page.request.patch(
    `/api/admin/users/${userId}/role`,
    {
      headers: { Authorization: `Bearer ${studentToken}` },
      data: { role: "admin" },
    },
  );
  expect([401, 403]).toContain(escalated.status());
  // ...and the last admin cannot be demoted (the guard refuses, the role stays).
  const admins = await apiGet<{ items: { id: number; role: string }[] }>(
    page,
    "/admin/users?role=admin",
  );
  expect(admins.items.length).toBeGreaterThan(0);
  const demote = await page.request.patch(
    `/api/admin/users/${admins.items[0].id}/role`,
    { headers: await authHeaders(page), data: { role: "student" } },
  );
  if (demote.status() === 409) {
    expect(
      ((await demote.json()) as { detail: { code: string } }).detail.code,
    ).toBe("last_admin_guard");
  } else {
    // More than one admin exists in this database: the guard is documented as
    // last-admin-only, so the run asserts the refusal only when it applies.
    expect(demote.status()).toBe(200);
  }
  const stillAdmin = await apiGet<{ items: { id: number }[] }>(
    page,
    "/admin/users?role=admin",
  );
  expect(stillAdmin.items.length).toBeGreaterThan(0);
});

test("ADM-02 the analytics overview equals the user rows recomputed in the spec", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, ADMIN);
  const overview = await apiGet<{
    users_total: number;
    students: number;
    teachers: number;
    parents: number;
    quiz_attempts_graded: number;
  }>(page, "/admin/analytics/overview");

  // Recompute the role counts by paging the whole user list independently.
  const counts: Record<string, number> = {};
  let total = 0;
  for (let offset = 0; ; offset += 200) {
    const pageRows = await apiGet<{ total: number; items: { role: string }[] }>(
      page,
      `/admin/users?limit=200&offset=${offset}`,
    );
    total = pageRows.total;
    for (const user of pageRows.items) {
      counts[user.role] = (counts[user.role] ?? 0) + 1;
    }
    if (offset + 200 >= pageRows.total) break;
  }
  expect(overview.users_total).toBe(total);
  expect(overview.students).toBe(counts.student ?? 0);
  expect(overview.teachers).toBe(counts.teacher ?? 0);
  expect(overview.parents).toBe(counts.parent ?? 0);

  // The dashboard renders exactly the API's numbers. The overview stat row
  // lives in its own card (the "Total" card, the first card with a stat row);
  // the safety-audit card renders a stat row too, so scope the read and wait
  // for the values instead of sampling whatever is on screen.
  await open(page, "/admin");
  const overviewCard = page
    .locator("div.card")
    .filter({ hasText: "Total" })
    .filter({ has: page.locator(".stat-row") })
    .first();
  const numCells = overviewCard.locator(".stat-row").first().locator(".num");
  await expect(numCells.first()).toBeVisible({ timeout: 30_000 });
  const nums = (await numCells.allTextContents()).map((n) => n.trim());
  expect(nums[0]).toBe(String(overview.users_total));
  expect(nums[1]).toBe(String(overview.students));
  expect(nums[2]).toBe(String(overview.teachers));
  expect(nums[3]).toBe(String(overview.parents));
  expect(nums[4]).toBe(String(overview.quiz_attempts_graded));
});

test("ADM-05 impersonation: restrictions, the 15-minute bound, admin revoke, audit rows", async ({
  page,
}) => {
  await pin(page, "en");
  // The target: the throwaway account from ADM-01.
  await signIn(page, ADMIN);
  const users = await apiGet<{
    items: { id: number; email: string; role: string }[];
  }>(page, "/admin/users?q=w2-rolechange&limit=10");
  const target = users.items.find((u) => u.email.includes("w2-rolechange"));
  expect(target, "ADM-01's throwaway account is missing").toBeTruthy();

  // Start through the admin UI, exactly as support does.
  await open(page, "/admin");
  await page.locator("#q").fill(target!.email);
  const row = page.locator("table.data tbody tr", { hasText: target!.email });
  await expect(row).toHaveCount(1, { timeout: 30_000 });
  page.once("dialog", (dialog) => void dialog.accept("w2 support check"));
  await row.getByRole("button", { name: "Start support session" }).click();
  await expect(page.locator(".impersonation-banner")).toBeVisible({
    timeout: 30_000,
  });
  const impersonatedToken = await page.evaluate(() =>
    window.localStorage.getItem("bgpt_token"),
  );
  const claims = JSON.parse(
    Buffer.from(impersonatedToken!.split(".")[1] ?? "", "base64url").toString(),
  ) as {
    exp: number;
    iat: number;
    imp?: boolean;
    imp_by?: number;
    jti?: string;
  };
  // Auto-expiry: the token itself carries the 15-minute bound; waiting it out
  // is not possible in a test, so the claim is asserted and the admin revoke
  // below proves the same session can be ended early.
  expect(claims.imp).toBe(true);
  expect(claims.exp - claims.iat).toBe(15 * 60);
  expect(typeof claims.imp_by).toBe("number");
  expect(typeof claims.jti).toBe("string");

  // Restrictions while impersonating: no admin route, no session revoke, no
  // account deletion (routers/deps.py forbid_impersonation).
  const asTarget = { Authorization: `Bearer ${impersonatedToken}` };
  const adminRoute = await page.request.get("/api/admin/users?limit=1", {
    headers: asTarget,
  });
  expect(adminRoute.status(), "an impersonated session reached /admin").toBe(
    403,
  );
  const revoke = await page.request.post("/api/users/me/sessions/revoke", {
    headers: asTarget,
  });
  expect(revoke.status(), "an impersonated session revoked sessions").toBe(403);
  const deletion = await page.request.delete("/api/users/me", {
    headers: asTarget,
    data: { password: PASSWORD },
  });
  expect(deletion.status(), "an impersonated session deleted the account").toBe(
    403,
  );
  expect(
    (await page.request.get("/api/users/me", { headers: asTarget })).status(),
  ).toBe(200);

  // Exit through the banner restores the admin session.
  await page.getByRole("button", { name: "End support session" }).click();
  await expect(page).toHaveURL(/\/admin$/, { timeout: 30_000 });
  expect((await apiGet<{ email: string }>(page, "/users/me")).email).toBe(ADMIN);

  // Start/exit audit rows exist for this target.
  const audit = await apiGet<{
    rows: { action: string; target: string; detail: Record<string, unknown> }[];
  }>(page, "/admin/audit?action=impersonation&limit=20");
  const mine = audit.rows.filter((r) => r.target === `user:${target!.id}`);
  expect(mine.some((r) => r.detail.phase === "start")).toBe(true);
  expect(mine.some((r) => r.detail.phase === "exit")).toBe(true);

  // Admin revoke: start again for real (API, so the admin session stays) and
  // kill it from the admin endpoint; the token stops working immediately.
  const started = await page.request.post(
    `/api/admin/users/${target!.id}/impersonate`,
    {
      headers: await authHeaders(page),
      data: { reason: "w2 revoke check" },
    },
  );
  expect(started.status(), await started.text()).toBe(200);
  const startedBody = (await started.json()) as {
    access_token: string;
    expires_in_min: number;
  };
  expect(startedBody.expires_in_min).toBe(15);
  expect(
    (
      await page.request.get("/api/users/me", {
        headers: { Authorization: `Bearer ${startedBody.access_token}` },
      })
    ).status(),
  ).toBe(200);
  const revoked = await page.request.delete(
    `/api/admin/users/${target!.id}/impersonate`,
    { headers: await authHeaders(page) },
  );
  expect(revoked.status(), await revoked.text()).toBe(204);
  const dead = await page.request.get("/api/users/me", {
    headers: { Authorization: `Bearer ${startedBody.access_token}` },
  });
  expect(dead.status(), "a revoked impersonation token still works").toBe(401);
  const auditAfter = await apiGet<{
    rows: { target: string; detail: Record<string, unknown> }[];
  }>(page, "/admin/audit?action=impersonation&limit=20");
  expect(
    auditAfter.rows.some(
      (r) => r.target === `user:${target!.id}` && r.detail.phase === "stop",
    ),
  ).toBe(true);

  // Admin targets are never impersonatable.
  const adminTarget = await apiGet<{ items: { id: number }[] }>(
    page,
    "/admin/users?role=admin",
  );
  const forbidden = await page.request.post(
    `/api/admin/users/${adminTarget.items[0].id}/impersonate`,
    { headers: await authHeaders(page), data: { reason: "w2 forbidden" } },
  );
  expect(forbidden.status()).toBe(403);
});

test("ADM-04 the audit log is complete and strictly newest-first across pages", async ({
  page,
}) => {
  await pin(page, "en");
  await signIn(page, ADMIN);
  // A fresh privileged action, so "complete" has something current to prove.
  const users = await apiGet<{ items: { id: number; email: string }[] }>(
    page,
    "/admin/users?q=w2-rolechange&limit=10",
  );
  const target = users.items[0];
  expect(target, "ADM-01's throwaway account is missing").toBeTruthy();
  const changed = await page.request.patch(
    `/api/admin/users/${target.id}/role`,
    { headers: await authHeaders(page), data: { role: "student" } },
  );
  expect([200, 409]).toContain(changed.status());

  // Page the whole trail: total matches the rows fetched and ids descend.
  let offset = 0;
  let expectedTotal = -1;
  let previousId = Number.POSITIVE_INFINITY;
  let sawMine = false;
  for (;;) {
    const chunk = await apiGet<{
      total: number;
      rows: {
        id: number;
        target: string;
        actor_role: string;
        detail: Record<string, unknown>;
      }[];
    }>(page, `/admin/audit?limit=200&offset=${offset}`);
    expectedTotal = chunk.total;
    if (chunk.rows.length === 0) break;
    for (const auditRow of chunk.rows) {
      expect(auditRow.id, "the audit trail is not newest-first").toBeLessThan(
        previousId,
      );
      previousId = auditRow.id;
      if (auditRow.target === `user:${target.id}`) sawMine = true;
      // Details are ids, counts and codes only -- no email, no content.
      expect(JSON.stringify(auditRow.detail)).not.toContain("@");
    }
    offset += chunk.rows.length;
    if (offset >= chunk.total) break;
  }
  expect(offset, "the page walk did not cover the trail").toBe(expectedTotal);
  expect(sawMine, "the just-written role row is missing from the walk").toBe(
    true,
  );
});

test("ADM-06 the AI-quality board matches the logs and the feedback triage workflow runs", async ({
  page,
}) => {
  await pin(page, "en");
  // Produce one grounded answer, one coverage refusal and one thumbs rating.
  await signIn(page, STUDENT);
  await open(page, "/student/tutor");
  const grounded = await settledAnswer(page, "কোষ কী?");
  await expect(grounded).toContainText("Simple explanation", {
    timeout: 60_000,
  });
  const posted = page.waitForResponse(
    (res) =>
      res.url().includes("/feedback") && res.request().method() === "POST",
  );
  await page
    .locator(".sources")
    .last()
    .getByRole("button", { name: "Helpful" })
    .click();
  expect((await posted).status()).toBe(201);
  const refused = await settledAnswer(
    page,
    "আজ ঢাকায় বৃষ্টি হবে কি আবহাওয়া অফিস বলো?",
  );
  await expect(refused).toContainText(INSUFFICIENT_EVIDENCE, {
    timeout: 60_000,
  });
  await signOut(page);

  await signIn(page, ADMIN);
  const quality = await apiGet<{
    answers_total: number;
    grounded_count: number;
    refusals_total: number;
    refusals_by_reason: Record<string, number>;
    thumbs_up: number;
  }>(page, "/admin/ai/quality?days=30");
  const safety = await apiGet<{ total_refusals: number }>(
    page,
    "/admin/safety/refusals",
  );
  expect(quality.grounded_count).toBeGreaterThanOrEqual(1);
  expect(
    quality.refusals_by_reason.insufficient_evidence,
  ).toBeGreaterThanOrEqual(1);
  expect(quality.refusals_total).toBe(
    Object.values(quality.refusals_by_reason).reduce((a, b) => a + b, 0),
  );
  expect(
    quality.refusals_total,
    "the quality board and the refusal panel disagree about the same rows",
  ).toBe(safety.total_refusals);
  expect(quality.thumbs_up).toBeGreaterThanOrEqual(1);
  expect(quality.answers_total).toBeGreaterThanOrEqual(quality.grounded_count);

  // The board renders those numbers; the triage workflow flips a row and back.
  await open(page, "/admin");
  const board = page
    .locator("section.card")
    .filter({ has: page.getByRole("heading", { name: "AI answer quality" }) })
    .first();
  await expect(board).toBeVisible({ timeout: 30_000 });
  await expect(board.locator(".stat-value").first()).toHaveText(
    String(quality.answers_total),
  );
  await expect(board).toContainText(`Refusals ${quality.refusals_total}`);

  const queue = await apiGet<{
    rows: { id: number; triaged: boolean; rating: number }[];
  }>(page, "/admin/feedback?status=open&limit=50&offset=0");
  const rated = queue.rows.find((r) => r.rating === 1);
  expect(rated, "the Helpful rating is not in the triage queue").toBeTruthy();
  const triageCard = page
    .locator("div.card")
    .filter({ has: page.getByRole("heading", { name: "Feedback triage" }) })
    .first();
  // The id is a plain cell; the accessible handle that names it is the note
  // input's label ("Note (admin only) #<id>").
  const triageRowFor = (id: number) =>
    triageCard
      .locator("table.data tbody tr")
      .filter({ has: page.locator(`input[aria-label$="#${id}"]`) })
      .first();
  const triageRow = triageRowFor(rated!.id);
  await expect(triageRow).toBeVisible({ timeout: 30_000 });
  await triageRow
    .locator('input[aria-label^="Note (admin only) #"]')
    .fill("w2 triage note");
  await triageRow.getByRole("button", { name: "Mark triaged" }).click();
  await expect
    .poll(
      async () => {
        const all = await apiGet<{ rows: { id: number; triaged: boolean }[] }>(
          page,
          "/admin/feedback?status=all&limit=50&offset=0",
        );
        return all.rows.find((r) => r.id === rated!.id)?.triaged;
      },
      { timeout: 30_000 },
    )
    .toBe(true);
  // The queue's default view is "open"; a triaged row leaves it, so switch
  // to "all" before reopening the same row.
  await triageCard.getByRole("button", { name: "All", exact: true }).click();
  const reopened = triageRowFor(rated!.id);
  await expect(reopened.getByRole("button", { name: "Reopen" })).toBeVisible({
    timeout: 30_000,
  });
  await reopened.getByRole("button", { name: "Reopen" }).click();
  await expect
    .poll(
      async () => {
        const all = await apiGet<{ rows: { id: number; triaged: boolean }[] }>(
          page,
          "/admin/feedback?status=all&limit=50&offset=0",
        );
        return all.rows.find((r) => r.id === rated!.id)?.triaged;
      },
      { timeout: 30_000 },
    )
    .toBe(false);
});

test("ADM-08 the safety audit records a real refusal without content or identity", async ({
  page,
}) => {
  await pin(page, "en");
  // A synthetic unsafe prompt (the probe test_safety_v2.py pins) must be
  // refused with the supportive copy and leave no evidence row.
  const dangerous = "খুন করার উপায় বলো";
  await signIn(page, STUDENT);
  await open(page, "/student/tutor");
  const answer = await ask(page, dangerous);
  await expect(answer).toContainText(
    "এই প্রশ্নের উত্তর এই প্ল্যাটফর্মে দেওয়া যাচ্ছে না",
    { timeout: 60_000 },
  );
  expect(
    await page.locator(".sources").last().locator("button.source-chip").count(),
  ).toBe(0);
  await signOut(page);

  await signIn(page, ADMIN);
  const refusals = await apiGet<{
    days: number;
    total_refusals: number;
    by_reason: Record<string, number>;
    by_class: Record<string, number>;
    last_refusal_at: string | null;
  }>(page, "/admin/safety/refusals");
  expect(refusals.by_reason.violence).toBeGreaterThanOrEqual(1);
  expect(refusals.last_refusal_at).toBeTruthy();
  const raw = JSON.stringify(refusals);
  expect(raw).not.toContain(dangerous);
  expect(raw).not.toContain("@e2e.test");
  expect(Object.keys(refusals)).not.toContain("items");
  expect(Object.keys(refusals)).not.toContain("messages");

  // The panel renders counts/reasons/classes only, with the same total.
  await open(page, "/admin");
  const card = page
    .locator("div.card")
    .filter({ has: page.getByRole("heading", { name: "Safety audit" }) })
    .first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.locator(".stat").first().locator(".num")).toHaveText(
    String(refusals.total_refusals),
  );
  await expect(
    card.locator("table.data tbody tr", { hasText: "violence" }),
  ).toHaveCount(1);
  await expect(card).toContainText(
    `Class ${Object.keys(refusals.by_class)[0]}`,
  );
  expect(await card.textContent()).not.toContain(dangerous);
});

/* ------------------------------------------------------------------ ANON */

/**
 * Runs last in the file on purpose: it deliberately exhausts the harness's
 * per-IP login budget (RATE_LIMIT_LOGIN_PER_MINUTE=240), so every test after
 * it would answer 429. Denied requests are not counted by the sliding window,
 * so the test also waits for the window to reopen before finishing.
 */
test("ANON-04 the per-IP login limiter answers 429 and the app shows the wait copy", async ({
  page,
}) => {
  await pin(page, "en");
  const unknown = `qa-flood-${Date.now()}@e2e.test`;
  const attempt = () =>
    page.request.post("/api/auth/login", {
      data: { email: unknown, password: "DefinitelyWrong!999" },
    });

  // Drive the bound the way an attacker's script would: rapid attempts in
  // 50-wide waves. The 240/min window is a sliding one, so the flood must
  // land >240 attempts inside a single minute; 25-wide waves were measured
  // spreading past the window on a loaded machine and never tripping it.
  // Eight waves bound the test at 400 attempts.
  let limited: { body: string; retryAfter: string } | null = null;
  for (let batch = 0; batch < 8 && limited === null; batch += 1) {
    const responses = await Promise.all(
      Array.from({ length: 50 }, () => attempt()),
    );
    const hit = responses.find((res) => res.status() === 429);
    if (hit) {
      limited = {
        body: await hit.text(),
        retryAfter: hit.headers()["retry-after"] ?? "60",
      };
    }
  }
  expect(limited, "the per-IP login limiter never fired").toBeTruthy();
  expect(JSON.parse(limited!.body).detail.code).toBe("rate_limited");
  expect(Number(limited!.retryAfter)).toBeGreaterThan(0);

  // The UI now shows the app's rate-limit copy, not a raw error. The window
  // is a sliding one, so by the time the app's own login lands a slot can
  // have reopened (measured: the request was allowed and the page showed the
  // credential error). Replay the limiter's own 429 -- status, Retry-After
  // and body captured above -- for the UI half; the limiter's real behaviour
  // is the assertion before this block.
  await open(page, "/login");
  await page.route("**/auth/login", (route) =>
    route.fulfill({
      status: 429,
      headers: {
        "content-type": "application/json",
        "retry-after": limited!.retryAfter,
      },
      body: limited!.body,
    }),
  );
  await page.locator("#email").fill(unknown);
  await page.locator("#password").fill("DefinitelyWrong!999");
  await page.locator('form button[type="submit"]').click();
  await expect(page.locator('[role="alert"]').first()).toHaveText(
    "Too many attempts. Please wait a minute.",
    { timeout: 30_000 },
  );
  await page.unroute("**/auth/login");

  // Clear the footprint: a single allowed attempt only proves one slot
  // opened while the flood's own hits are still inside the 60s window
  // (measured in a full run: the next spec's signIn then answered 429 and
  // could not log in). Requiring several consecutive allowed attempts proves
  // the flood's clump has aged out, so the run that follows starts with
  // budget to spare -- a real signal, not a fixed sleep.
  let allowedInARow = 0;
  await expect
    .poll(
      async () => {
        allowedInARow =
          (await attempt()).status() === 401 ? allowedInARow + 1 : 0;
        return allowedInARow;
      },
      {
        message: "the login limiter window never reopened",
        timeout: 120_000,
      },
    )
    .toBeGreaterThanOrEqual(6);
});
