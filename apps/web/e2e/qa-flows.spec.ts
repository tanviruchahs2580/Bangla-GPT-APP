import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

/**
 * Phase 7 acceptance flows: the §8.3 flow-matrix gaps the other browser specs
 * do not drive (see `.qa-work/audit/FLOWS/coverage_map.csv`).
 *
 * Everything here follows the smoke.spec.ts pattern: the shipped UI against
 * the real API with the deterministic `mock` provider and the seeded role
 * accounts (seed_e2e_users.py). Nothing is mocked at the HTTP layer; no fixed
 * sleeps -- every wait is a URL, a visible element or a polled API response.
 *
 * Deliberate limits, stated where they bite:
 *  * X-11 -- the harness pins `AI_GENERATION_ENABLED` on (playwright.config.ts
 *    env block, not editable from a spec), so the DISABLED path is covered by
 *    apps/api/tests/test_qa_kill_switch.py and this file covers the ENABLED
 *    path (an inverted default must not pass both at once).
 *  * ADM-03 -- the admin UI has no dry-run control, so the dry-run (the
 *    compliance-evidence path) is exercised through the app's own API and the
 *    real sweep through the UI's two-step confirm.
 *  * ADM-05 -- auto-expiry (15 minutes) and the admin revoke endpoint cannot
 *    be waited out in an e2e run; start/banner/exit/audit are driven.
 *  * STU-16/STU-13 -- registration is per-IP limited to 10/min; this file
 *    makes three registrations in total.
 */

const PASSWORD = "E2ePass!2345";
const STUDENT = "student1@e2e.test";
const STUDENT2 = "student2@e2e.test";
const TEACHER = "teacher1@e2e.test";
const PARENT = "parent1@e2e.test";
const ADMIN = "admin1@e2e.test";
const SCHOOL_ADMIN = "schooladmin1@e2e.test";

/** The one known in-corpus question (class-6 science, bundled sample corpus). */
const QUESTION = "কোষ কী?";

// Each test drives several roles and sometimes a background job; the
// per-assertion timeout stays tight, the per-test budget is generous.
test.describe.configure({ timeout: 5 * 60_000 });

// Pin the UI language to English so the selectors below are stable (the app
// defaults to Bangla); i18n coverage belongs to the unit suite.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    window.localStorage.setItem("bgpt_lang", "en"),
  );
});

async function open(page: Page, path: string): Promise<void> {
  await page.goto(path, { waitUntil: "domcontentloaded" });
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
  await expect(page).not.toHaveURL(/\/login$/);
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem("bgpt_token")))
    .toBeTruthy();
}

async function signOut(page: Page): Promise<void> {
  await page
    .locator("header")
    .getByRole("button", { name: "Log out" })
    .click();
  await expect(page).toHaveURL(/\/login$/);
}

/** Bearer headers for the CURRENT session, for API-through-the-app calls. */
async function authHeaders(page: Page): Promise<{ Authorization: string }> {
  const token = await page.evaluate(() =>
    window.localStorage.getItem("bgpt_token"),
  );
  expect(token, "no session token in localStorage").toBeTruthy();
  return { Authorization: `Bearer ${token}` };
}

async function apiGet<T>(page: Page, path: string): Promise<T> {
  const res = await page.request.get(`/api${path}`, {
    headers: await authHeaders(page),
  });
  expect(res.status(), `GET ${path}: ${await res.text()}`).toBe(200);
  return (await res.json()) as T;
}

/** One failed /login attempt; returns the inline error copy the user sees. */
async function refusedLogin(
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
  await expect(page).toHaveURL(/\/login$/);
  return ((await alert.textContent()) ?? "").trim();
}

/** A grounded, streamed mock answer; returns the answer bubble locator. */
async function askAndAwaitAnswer(page: Page, question: string) {
  const box = page.getByRole("textbox", {
    name: "Ask anything from your textbook…",
  });
  await box.fill(question);
  await page.getByRole("button", { name: "Send" }).click();
  const answer = page.locator(".bubble.assistant").last();
  await expect(answer).toContainText("Simple explanation", {
    timeout: 60_000,
  });
  return answer;
}

/** A single-use parent invite code, issued by the signed-in student. */
async function generateInvite(page: Page): Promise<string> {
  const res = await page.request.post("/api/students/me/invite-code", {
    headers: await authHeaders(page),
    data: {},
  });
  expect(res.status(), await res.text()).toBe(201);
  return ((await res.json()) as { code: string }).code;
}

/** One real, graded quiz attempt through the API. */
async function gradedQuizAttempt(page: Page): Promise<{
  attemptId: number;
  scorePct: number;
  total: number;
  correct: number;
}> {
  const me = await apiGet<{ profile_id: number }>(page, "/users/me");
  const started = await page.request.post("/api/quizzes", {
    headers: await authHeaders(page),
    data: {
      student_id: me.profile_id,
      subject: "science",
      class_level: 6,
      num_questions: 3,
    },
  });
  expect(started.status(), await started.text()).toBe(200);
  const quiz = (await started.json()) as {
    attempt_id: number;
    questions: { id: string }[];
  };
  expect(quiz.questions.length).toBeGreaterThan(0);
  const submitted = await page.request.post(
    `/api/quizzes/${quiz.attempt_id}/submit`,
    {
      headers: await authHeaders(page),
      data: { answers: quiz.questions.map(() => 0) },
    },
  );
  expect(submitted.status(), await submitted.text()).toBe(200);
  const result = (await submitted.json()) as {
    score_pct: number;
    total: number;
    correct: number;
  };
  return {
    attemptId: quiz.attempt_id,
    scorePct: result.score_pct,
    total: result.total,
    correct: result.correct,
  };
}

/* ------------------------------------------------------------------ ANON */

test("ANON-02 status page shows real component checks and no sensitive payload", async ({
  page,
}) => {
  // The public payload is presence/booleans only (routers/system.py:75). Assert
  // the shape, the absence of anything profileable, and that the page renders
  // exactly the components the API reported -- a static status page would pass
  // a DOM-only check but fail the count/name comparison.
  const res = await page.request.get("/api/status");
  expect(res.status()).toBe(200);
  const body = (await res.json()) as {
    status: string;
    components: { name: string; ok: boolean; detail: string }[];
    checked_at: string;
  };
  expect(["ok", "degraded"]).toContain(body.status);
  expect(body.components.length).toBeGreaterThan(0);
  for (const c of body.components) {
    expect(typeof c.name).toBe("string");
    expect(typeof c.ok).toBe("boolean");
    expect(typeof c.detail).toBe("string");
  }
  const raw = JSON.stringify(body).toLowerCase();
  for (const leak of [
    "users_total",
    "students",
    "version",
    "environment",
    "@",
    "secret",
    "token",
  ]) {
    expect(raw, `the public status payload mentions ${leak}`).not.toContain(
      leak,
    );
  }

  await open(page, "/status");
  await expect(page.locator(".status-item")).toHaveCount(body.components.length);
  for (const c of body.components) {
    await expect(
      page.locator(".status-item strong", { hasText: c.name }),
    ).toHaveCount(1);
  }
  await expect(page.locator(".status-hero")).toBeVisible();
});

test("ANON-04 unknown email and wrong password give the same refusal, and success signs in", async ({
  page,
}) => {
  const unknown = `qa-nobody-${Date.now()}@e2e.test`;
  const unknownCopy = await refusedLogin(page, unknown, PASSWORD);
  expect(unknownCopy.length).toBeGreaterThan(0);
  // ONE wrong password on a seeded account: the per-account lockout trips at 5
  // (apps/api/src/bangla_gpt_api/routers/auth.py:83) and the successful login
  // below resets the counter, so this run leaves no lockout behind.
  const wrongCopy = await refusedLogin(page, STUDENT, "DefinitelyWrong!999");
  expect(
    wrongCopy,
    "an unknown email and a wrong password must be indistinguishable",
  ).toBe(unknownCopy);

  await signIn(page, STUDENT);
  await expect(page).toHaveURL(/\/student$/);
});

/* --------------------------------------------------------------------- X */

test("X-11 kill switch (generation enabled): tutor, search, reader and quizzes all work", async ({
  page,
}) => {
  // The disabled path is covered by apps/api/tests/test_qa_kill_switch.py --
  // the harness pins AI_GENERATION_ENABLED on in playwright.config.ts and a
  // spec may not edit the config. This asserts the enabled path end to end so
  // an inverted default cannot pass both tests at once.
  await signIn(page, STUDENT);

  const ask = await page.request.post("/api/tutor/ask", {
    headers: await authHeaders(page),
    data: { question: QUESTION, class_level: 6, subject: "science" },
  });
  expect(ask.status(), await ask.text()).toBe(200);
  const answer = (await ask.json()) as {
    answer: string;
    grounded: boolean;
    refused_reason: string | null;
    sources: unknown[];
  };
  expect(answer.grounded).toBe(true);
  expect(answer.refused_reason).toBeNull();
  expect(answer.sources.length).toBeGreaterThan(0);
  expect(answer.answer).toContain("কোষ");
  expect(
    answer.answer,
    "the degraded-mode copy appeared although generation is enabled",
  ).not.toContain("সাময়িকভাবে বন্ধ");

  // Reader: the corpus the tutor cites is browsable.
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
  const chapter = await apiGet<{ sections: { text: string }[] }>(
    page,
    `/learn/subjects/${encodeURIComponent(subjects[0].subject)}/chapters/${encodeURIComponent(
      chapters[0].chapter,
    )}?class_level=6`,
  );
  expect(chapter.sections.length).toBeGreaterThan(0);
  expect(chapter.sections.some((s) => s.text.trim().length > 0)).toBe(true);

  // Search: the unified search still answers.
  const search = await apiGet<{ hits: unknown[] }>(
    page,
    `/search?q=${encodeURIComponent("কোষ")}`,
  );
  expect(search.hits.length).toBeGreaterThan(0);

  // Quizzes: generation-independent, graded through the real API.
  const quiz = await gradedQuizAttempt(page);
  expect(quiz.total).toBeGreaterThan(0);
});

test("X-01 role switching in one browser leaves no student data in the teacher shell", async ({
  page,
}) => {
  await signIn(page, STUDENT);

  // Produce real student state: open a chapter (writes the user-scoped
  // `lastChapter` key) and download its offline copy (IndexedDB `bgpt-offline`,
  // src/lib/offlineStore.ts:29).
  const subjects = await apiGet<{ subject: string }[]>(
    page,
    "/learn/subjects?class_level=6",
  );
  const chapters = await apiGet<{ chapter: string }[]>(
    page,
    `/learn/subjects/${encodeURIComponent(subjects[0].subject)}/chapters?class_level=6`,
  );
  // `?class=` is what the subject list links carry; without it the reader has
  // no class level and records neither progress nor `lastChapter`.
  await open(
    page,
    `/student/learn/${encodeURIComponent(subjects[0].subject)}/${encodeURIComponent(
      chapters[0].chapter,
    )}?class=6`,
  );
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem("lastChapter")))
    .toBeTruthy();
  const download = page.getByRole("button", { name: "Download chapter" });
  await expect(download).toBeVisible();
  await download.click();
  // The button's accessible name is its fixed aria-label; the visible label
  // flips to "Saved" once the copy is in IndexedDB.
  await expect(
    download,
    "the offline copy never reported itself saved",
  ).toContainText("Saved");
  expect(
    await page.evaluate(async () =>
      (await indexedDB.databases()).map((d) => d.name),
    ),
  ).toContain("bgpt-offline");

  await signOut(page);

  await signIn(page, TEACHER);
  await expect(page).toHaveURL(/\/teacher$/);

  // The session token now belongs to the teacher...
  const me = await apiGet<{ email: string }>(page, "/users/me");
  expect(me.email).toBe(TEACHER);

  // ...every user-scoped key the student left is gone (api.ts
  // USER_STORAGE_KEYS), while device preferences deliberately survive (F-036).
  const storage = await page.evaluate(() => ({
    lastChapter: window.localStorage.getItem("lastChapter"),
    lowData: window.localStorage.getItem("bgpt-lowdata"),
    adminToken: window.localStorage.getItem("bgpt_admin_token_backup"),
    impersonating: window.localStorage.getItem("bgpt_impersonating"),
    lang: window.localStorage.getItem("bgpt_lang"),
  }));
  expect(storage.lastChapter).toBeNull();
  expect(storage.lowData).toBeNull();
  expect(storage.adminToken).toBeNull();
  expect(storage.impersonating).toBeNull();
  expect(
    storage.lang,
    "the device language preference must survive a sign-out",
  ).toBe("en");

  // The downloaded offline chapter is gone with the session.
  await expect
    .poll(async () =>
      page.evaluate(async () =>
        (await indexedDB.databases()).map((d) => d.name),
      ),
    )
    .not.toContain("bgpt-offline");

  // No student data in the teacher shell: neither the name nor the student route.
  await expect(page.locator("body")).not.toContainText("E2E Student");
  await open(page, "/student/tutor");
  await expect
    .poll(() => new URL(page.url()).pathname, { timeout: 20_000 })
    .not.toBe("/student/tutor");

  // And back: the student shell carries no teacher chrome either.
  await signOut(page);
  await signIn(page, STUDENT);
  await expect(page).toHaveURL(/\/student$/);
  await expect(page.locator("aside.sidebar")).toHaveCount(0);
  await expect(page.locator("nav.bottombar")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("E2E Teacher");
});

/* ------------------------------------------------------------------- ADM */

test("ADM-05 impersonation: start, support banner, exit, audit trail", async ({
  page,
}) => {
  await signIn(page, ADMIN);
  await expect(page).toHaveURL(/\/admin$/);

  // Find the seeded student through the admin search UI, as a support agent would.
  await page.locator("#q").fill(STUDENT);
  const row = page.locator("table.data tbody tr", { hasText: STUDENT });
  await expect(row).toHaveCount(1, { timeout: 30_000 });
  const studentUserId = Number(
    (await row.locator("td").first().textContent())?.trim(),
  );
  expect(Number.isInteger(studentUserId)).toBe(true);

  // The reason prompt is part of the product flow; accept it with a real reason.
  page.once("dialog", (dialog) => void dialog.accept("qa e2e support check"));
  await row.getByRole("button", { name: "Start support session" }).click();

  // The impersonated session lands on the target's home with the banner naming them.
  await expect(page).toHaveURL(/\/student$/, { timeout: 30_000 });
  const banner = page.locator(".impersonation-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toHaveAttribute("role", "status");
  await expect(banner).toContainText("E2E Student");
  await expect(banner).toContainText("support session");
  const impersonatedMe = await apiGet<{ email: string }>(page, "/users/me");
  expect(impersonatedMe.email).toBe(STUDENT);

  // Exit restores the admin session and removes the banner.
  await page.getByRole("button", { name: "End support session" }).click();
  await expect(page).toHaveURL(/\/admin$/, { timeout: 30_000 });
  await expect(page.locator(".impersonation-banner")).toHaveCount(0);
  const restoredMe = await apiGet<{ email: string }>(page, "/users/me");
  expect(restoredMe.email).toBe(ADMIN);

  // Both ends of the session are in the audit trail, and the trail is newest-first.
  const audit = await apiGet<{
    rows: {
      id: number;
      action: string;
      target: string;
      detail: Record<string, unknown>;
    }[];
  }>(page, "/admin/audit?action=impersonation&limit=20");
  const mine = audit.rows.filter((r) => r.target === `user:${studentUserId}`);
  expect(
    mine.some((r) => r.detail.phase === "start"),
    "no impersonation start audit row",
  ).toBe(true);
  expect(
    mine.some((r) => r.detail.phase === "exit"),
    "no impersonation exit audit row",
  ).toBe(true);
  const ids = audit.rows.map((r) => r.id);
  expect(ids).toEqual([...ids].sort((a, b) => b - a));
});

test("ADM-03 retention purge: dry-run shape, real run through the UI, audit row", async ({
  page,
}) => {
  await signIn(page, ADMIN);
  const headers = await authHeaders(page);

  // Dry-run through the app's API: the compliance-evidence path, no writes.
  const dryRes = await page.request.post(
    "/api/admin/maintenance/purge?dry_run=true",
    { headers },
  );
  expect(dryRes.status(), await dryRes.text()).toBe(200);
  const dry = (await dryRes.json()) as Record<string, unknown>;
  expect(dry.dry_run).toBe(true);
  const COUNT_KEYS = [
    "conversations_deleted",
    "chat_messages_deleted",
    "password_resets_deleted",
    "email_verifications_deleted",
    "used_invites_deleted",
    "analytics_events_deleted",
    "answer_log_deleted",
    "ai_usage_deleted",
  ];
  for (const key of COUNT_KEYS) {
    expect(typeof dry[key], `dry-run report is missing ${key}`).toBe("number");
    expect(dry[key] as number).toBeGreaterThanOrEqual(0);
  }

  // The real run through the shipped UI: two-step confirm, then the status line.
  await page.getByRole("button", { name: "Purge expired data" }).click();
  await page.getByRole("button", { name: "Purge expired data" }).click();
  const status = page
    .locator('main p[role="status"]')
    .filter({ hasText: "Purged" });
  await expect(status).toBeVisible({ timeout: 30_000 });
  for (const key of COUNT_KEYS) {
    await expect(status).toContainText(`${key}:`);
  }

  // "Only the intended rows": nothing expired is left after the sweep, so the
  // very same report now reads zero everywhere.
  const afterRes = await page.request.post(
    "/api/admin/maintenance/purge?dry_run=true",
    { headers },
  );
  expect(afterRes.status()).toBe(200);
  const after = (await afterRes.json()) as Record<string, number>;
  for (const key of COUNT_KEYS) {
    expect(after[key], `${key} still non-zero after the sweep`).toBe(0);
  }

  // And the sweep left an audit row, counts-only.
  const audit = await apiGet<{
    rows: { action: string; target: string; detail: Record<string, unknown> }[];
  }>(page, "/admin/audit?action=purge&limit=10");
  expect(audit.rows.length).toBeGreaterThan(0);
  expect(audit.rows[0].target).toBe("retention_sweep");
  for (const value of Object.values(audit.rows[0].detail)) {
    expect(typeof value).toBe("number");
  }
});

test("ADM-07 k-anonymity: a one-student cohort is suppressed and the floor cannot be lowered", async ({
  page,
}) => {
  await signIn(page, STUDENT);
  // One graded attempt -> a (class 6, science) cohort of ONE student, which the
  // k-anonymity floor (govt_report.MIN_CELL_FLOOR = 5) must suppress.
  const quiz = await gradedQuizAttempt(page);
  expect(quiz.attemptId).toBeGreaterThan(0);

  await signOut(page);
  await signIn(page, ADMIN);

  const ok = await page.request.get(
    "/api/admin/reports/aggregate?format=json&min_cell=5",
    { headers: await authHeaders(page) },
  );
  expect(ok.status(), await ok.text()).toBe(200);
  const payload = (await ok.json()) as {
    meta: {
      min_cell: number;
      suppressed_cells: number;
      total_students_included: number;
      pii_checked: boolean;
    };
    rows: { class_level: number; subject: string; students: number }[];
  };
  expect(payload.meta.min_cell).toBe(5);
  expect(payload.meta.pii_checked).toBe(true);
  expect(
    payload.meta.suppressed_cells,
    "the one-student cohort was not counted as suppressed",
  ).toBeGreaterThanOrEqual(1);
  const leaked = payload.rows.find(
    (r) => r.class_level === 6 && r.subject === "science" && r.students < 5,
  );
  expect(leaked, "a below-threshold cell was released").toBeUndefined();
  for (const r of payload.rows) {
    expect(
      r.students,
      `cell ${r.class_level}/${r.subject} is below the k-anonymity floor`,
    ).toBeGreaterThanOrEqual(5);
  }
  expect(JSON.stringify(payload)).not.toMatch(/@e2e\.test/);

  // The requester cannot lower the guarantee: min_cell is floor-bounded.
  const lowered = await page.request.get(
    "/api/admin/reports/aggregate?format=json&min_cell=1",
    { headers: await authHeaders(page) },
  );
  expect(lowered.status(), "min_cell below the floor must be refused").toBe(
    422,
  );
});

/* ------------------------------------------------------------------- SAD */

test("SAD-03 school A cannot read or write school B by ID", async ({ page }) => {
  // Fixture: a second school, created the way an operator creates one, plus one
  // classroom in it so there is a real ID to tamper with.
  await signIn(page, ADMIN);
  const schoolBName = `QA School B ${Date.now()}`;
  await page.locator("#nschool").fill(schoolBName);
  await page.getByRole("button", { name: "Create school" }).click();
  await expect(
    page.locator("table.data tbody td", { hasText: schoolBName }),
  ).toBeVisible({ timeout: 30_000 });

  const schools = await apiGet<{ id: number; name: string; code: string }[]>(
    page,
    "/admin/schools",
  );
  const schoolB = schools.find((s) => s.name === schoolBName);
  expect(schoolB, "the created school is not in /admin/schools").toBeTruthy();
  const classRes = await page.request.post(
    `/api/schools/${schoolB!.id}/classes`,
    {
      headers: await authHeaders(page),
      data: { class_level: 6, section: "QB" },
    },
  );
  expect(classRes.status(), await classRes.text()).toBe(201);

  await signOut(page);
  await signIn(page, SCHOOL_ADMIN);
  await expect(page).toHaveURL(/\/school$/);
  const headers = await authHeaders(page);

  // Endpoints that take an ID, plus an admin-only one.
  const tampers = [
    `/api/school/overview?school_id=${schoolB!.id}`,
    `/api/school/students?school_id=${schoolB!.id}`,
    `/api/school/classes?school_id=${schoolB!.id}`,
    `/api/admin/schools/${schoolB!.id}/invites`,
  ];
  for (const url of tampers) {
    const res = await page.request.get(url, { headers });
    expect(res.status(), `${url} was not refused`).toBe(403);
    const text = await res.text();
    expect(text, `${url} leaked the other school's name`).not.toContain(
      schoolBName,
    );
    expect(text, `${url} leaked the other school's code`).not.toContain(
      schoolB!.code,
    );
  }
  const write = await page.request.post(
    `/api/schools/${schoolB!.id}/classes`,
    { headers, data: { class_level: 7, section: "QB" } },
  );
  expect(write.status(), "school A could create a class in school B").toBe(
    403,
  );

  // The own-school path still works, so the 403s above are scoping, not breakage.
  const own = await apiGet<{ name: string }>(page, "/school/overview");
  expect(own.name).toBe("E2E School");
  await expect(page.locator("body")).toContainText("E2E School");
  await expect(page.locator("body")).not.toContainText(schoolBName);
});

/* ------------------------------------------------------------------- PAR */

test("PAR-04 another child's data cannot be read by ID", async ({ page }) => {
  // Link parent1 to student1 so the test proves the CONTRAST: linked 200,
  // unlinked 404. A repeat link answers 409 (already linked) and is the same
  // acceptable end state when an earlier spec already consumed a code.
  await signIn(page, STUDENT);
  const code = await generateInvite(page);
  await signOut(page);

  // A real other child (seeded student2), for the existence-leak comparison.
  await signIn(page, STUDENT2);
  const otherChild = await apiGet<{ profile_id: number }>(page, "/users/me");
  await signOut(page);

  await signIn(page, PARENT);
  const link = await page.request.post("/api/parents/link/invite", {
    headers: await authHeaders(page),
    data: { code },
  });
  expect(
    [201, 409],
    `link answered ${link.status()}: ${await link.text()}`,
  ).toContain(link.status());

  const children = await apiGet<{ student_id: number; name: string }[]>(
    page,
    "/parents/me/children",
  );
  const ownChild = children.find((c) => c.name === "E2E Student");
  expect(ownChild, "the linked child is not listed").toBeTruthy();
  expect(otherChild.profile_id).not.toBe(ownChild!.student_id);

  // The own child's data loads...
  const ok = await page.request.get(
    `/api/parents/me/children/${ownChild!.student_id}/progress`,
    { headers: await authHeaders(page) },
  );
  expect(ok.status()).toBe(200);

  // ...and someone else's existing child is refused exactly like a nonexistent
  // id: same status, byte-identical body, no existence leak.
  const refused = [
    `/parents/me/children/${otherChild.profile_id}/progress`,
    `/parents/me/children/${otherChild.profile_id}/activity`,
    `/parents/me/children/${otherChild.profile_id}/report`,
    `/parents/me/children/987654321/progress`,
  ];
  const bodies: string[] = [];
  for (const path of refused) {
    const res = await page.request.get(`/api${path}`, {
      headers: await authHeaders(page),
    });
    expect(res.status(), `${path} was not refused`).toBe(404);
    const text = await res.text();
    expect(text, `${path} did not answer not_linked: ${text}`).toContain(
      "not_linked",
    );
    expect(text, `${path} leaked the child's name`).not.toContain(
      "E2E Visual",
    );
    bodies.push(text);
  }
  for (const body of bodies) {
    expect(
      body,
      "an existing-but-unlinked child and a nonexistent one must be indistinguishable",
    ).toBe(bodies[0]);
  }

  // The dashboard itself only ever renders the linked child. Navigate rather
  // than assume: the page was loaded before the link call above, so without a
  // fresh load the assertion races the (already-fetched) empty child list.
  // Found in the first full-suite run: the test passed standalone and failed
  // after smoke.spec.ts had consumed an invite code, because the stale page
  // still showed "My children —".
  await page.goto("/parent", { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toContainText("E2E Student");
  await expect(page.locator("body")).not.toContainText("E2E Visual Student");
});

test("PAR-03 parent report is built from real activity and renders in Bangla", async ({
  page,
}) => {
  // Real activity: a graded attempt, created through the app.
  await signIn(page, STUDENT);
  const code = await generateInvite(page);
  await gradedQuizAttempt(page);
  await signOut(page);

  await signIn(page, PARENT);
  const link = await page.request.post("/api/parents/link/invite", {
    headers: await authHeaders(page),
    data: { code },
  });
  expect([201, 409]).toContain(link.status());

  // The API report for the child is the source of truth for "the sentences are
  // drawn from real data": the UI must render exactly its numbers, and the
  // suggestion sentence must name the report's own weak chapters.
  const children = await apiGet<{ student_id: number; name: string }[]>(
    page,
    "/parents/me/children",
  );
  const child = children.find((c) => c.name === "E2E Student");
  expect(child, "the linked child is not listed").toBeTruthy();
  const report = await apiGet<{
    quizzes_taken: number;
    avg_score_pct: number | null;
    chapters_read: number;
    questions_asked: number;
    weak_chapters: string[];
    strengths: string[];
  }>(
    page,
    `/parents/me/children/${child!.student_id}/report?period=weekly`,
  );
  expect(report.quizzes_taken).toBeGreaterThanOrEqual(1);

  const row = page.locator("table tbody tr", { hasText: "E2E Student" });
  await expect(row).toHaveCount(1, { timeout: 30_000 });
  await row.getByRole("button", { name: "My progress" }).click();
  const reportCard = page
    .locator("div.card")
    .filter({ hasText: "Quizzes taken" })
    .first();
  await expect(reportCard).toBeVisible({ timeout: 30_000 });

  // The four headline numbers are the API's numbers.
  const nums = (await reportCard.locator(".stat .num").allTextContents()).map(
    (n) => n.trim(),
  );
  expect(nums[0]).toBe(String(report.quizzes_taken));
  expect(nums[1]).toBe(
    report.avg_score_pct == null
      ? "—"
      : `${Math.round(report.avg_score_pct)}%`,
  );
  expect(nums[2]).toBe(String(report.chapters_read));
  expect(nums[3]).toBe(String(report.questions_asked));

  const cardText = (await reportCard.textContent()) ?? "";
  const suggestion = (cardText.split("Suggestion:")[1] ?? "").trim();
  expect(suggestion.length).toBeGreaterThan(0);
  expect(suggestion).not.toContain("undefined");
  expect(suggestion).not.toContain("{");
  if (report.weak_chapters.length > 0) {
    expect(cardText).toContain("Weak chapters");
    expect(
      report.weak_chapters.some((c) => suggestion.includes(c)),
      `the suggestion does not name a real weak chapter: ${suggestion}`,
    ).toBe(true);
  }

  // Switch to Bangla: the same report renders its sentence in Bangla script.
  await page
    .locator("header")
    .getByRole("button", { name: "Language" })
    .click();
  await expect(page.locator("html")).toHaveAttribute("lang", "bn");
  const bnCard = page
    .locator("div.card")
    .filter({ hasText: "পরামর্শ" })
    .first();
  await expect(bnCard).toBeVisible();
  const bnText = (await bnCard.textContent()) ?? "";
  expect(bnText).toMatch(/[\u0980-\u09FF]/);
  expect(bnText).toContain("পরামর্শ");
});

/* ------------------------------------------------------------------- STU */

test("STU-13 notification bell: unread count, item copy, read semantics", async ({
  page,
}) => {
  // A fresh parent account makes the bell deterministic (zero notifications
  // before the link). Registration #1 of 3 in this file.
  const parentEmail = `qa-parent-${Date.now()}@e2e.test`;

  // The student issues a single-use invite code from their own profile.
  await signIn(page, STUDENT);
  await open(page, "/student/me");
  await page.getByRole("button", { name: "Generate code" }).click();
  const code = (await page.locator(".invite-code").textContent())?.trim() ?? "";
  expect(code).toMatch(/^BGPT-[A-Z0-9]+$/);
  await signOut(page);

  await open(page, "/register");
  await page.locator("#role").selectOption("parent");
  await page.locator("#name").fill("QA Parent");
  await page.locator("#remail").fill(parentEmail);
  await page.locator("#rpassword").fill(PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/parent$/, { timeout: 30_000 });

  // Before the link: no unread badge, and the empty state.
  const bell = page.getByRole("button", { name: "Notifications" });
  await expect(page.locator(".notif-badge")).toHaveCount(0);
  await bell.click();
  await expect(page.locator(".notif-empty")).toHaveText(
    "No notifications yet",
  );
  await page.keyboard.press("Escape");
  await expect(page.locator(".notif-panel")).toHaveCount(0);

  // The link notifies this parent (routers/parent.py notify_user).
  await page.locator("#icode").fill(code);
  await page.getByRole("button", { name: "Link" }).click();
  await expect(
    page.getByText("Linked to your child's account."),
  ).toBeVisible();

  // Opening the bell refreshes it; the new notification arrives unread.
  await bell.click();
  const item = page.locator(".notif-item").first();
  await expect(item).toHaveCount(1, { timeout: 20_000 });
  await expect(item).toContainText("Guardian link established");
  await expect(item).toHaveClass(/unread/);
  await expect(page.locator(".notif-badge")).toHaveText("1");

  // Opening it marks it read and clears the badge.
  await item.click();
  await expect(page.locator(".notif-badge")).toHaveCount(0);
  const feed = await apiGet<{
    unread_count: number;
    items: { read_at: string | null; code: string }[];
  }>(page, "/notifications");
  expect(feed.unread_count).toBe(0);
  expect(feed.items[0].code).toBe("notif_parent_linked");
  expect(feed.items[0].read_at).not.toBeNull();
});

test("STU-16 export returns the full sections and deletion removes the account", async ({
  page,
}) => {
  // Throwaway account (registration #2 of 3 in this file).
  const email = `qa-throwaway-${Date.now()}@e2e.test`;
  await open(page, "/register");
  await page.locator("#name").fill("QA Throwaway");
  await page.locator("#remail").fill(email);
  await page.locator("#rpassword").fill(PASSWORD);
  await page.locator("#consent").check();
  await page.locator('form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/student$/, { timeout: 30_000 });

  // Export through the shipped UI: the download is the JSON the user gets.
  await open(page, "/student/me");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download my data" }).click();
  const download = await downloadPromise;
  const path = await download.path();
  expect(path, "the export download produced no file").toBeTruthy();
  const exported = JSON.parse(readFileSync(path!, "utf8")) as Record<
    string,
    unknown
  >;
  expect(exported.schema_version).toBe("2");
  expect((exported.user as { email: string }).email).toBe(email);
  for (const section of [
    "profile",
    "quiz_attempts",
    "conversations",
    "chat_messages",
    "learning_activity",
    "notes",
    "notifications",
    "chapter_progress",
    "answer_log",
    "analytics_events",
  ]) {
    expect(
      exported,
      `the export is missing the ${section} section`,
    ).toHaveProperty(section);
  }

  // Deletion needs the current password (F-142), then the session ends.
  const token = await page.evaluate(() =>
    window.localStorage.getItem("bgpt_token"),
  );
  await page.getByRole("button", { name: "Delete my account" }).click();
  await page.locator("#del-password").fill(PASSWORD);
  await page.getByRole("button", { name: "Yes, delete" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(
    await page.evaluate(() => window.localStorage.getItem("bgpt_token")),
  ).toBeNull();

  // The stolen copy of the token is dead...
  const after = await page.request.get("/api/users/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(after.status()).toBe(401);
  // ...the credentials no longer authenticate...
  const relogin = await page.request.post("/api/auth/login", {
    data: { email, password: PASSWORD },
  });
  expect(relogin.status(), "a deleted account could still log in").toBe(401);
  // ...and the row is gone for real: the same email registers again.
  const reRegister = await page.request.post("/api/auth/register", {
    data: {
      email,
      password: PASSWORD,
      name: "QA Throwaway",
      role: "student",
      class_level: 6,
      guardian_consent: true,
    },
  });
  expect(reRegister.status(), await reRegister.text()).toBe(201);
});

test("STU-08 save to notes, list, delete, and thumbs feedback reaches triage", async ({
  page,
}) => {
  await signIn(page, STUDENT);
  const headers = await authHeaders(page);
  const notesBefore = (await (
    await page.request.get("/api/notes", { headers })
  ).json()) as unknown[];

  await open(page, "/student/tutor");
  await askAndAwaitAnswer(page, QUESTION);
  const surface = page.locator(".sources").last();
  const save = surface.getByRole("button", { name: "Save as note" });
  await expect(save).toBeVisible();
  await save.click();
  await expect
    .poll(
      async () =>
        (
          (await (
            await page.request.get("/api/notes", { headers })
          ).json()) as unknown[]
        ).length,
      { message: "the saved answer never reached /notes" },
    )
    .toBe(notesBefore.length + 1);

  // Feedback: both controls carry accessible names, and Helpful really posts.
  const helpful = surface.getByRole("button", { name: "Helpful" });
  await expect(helpful).toBeVisible();
  await expect(surface.getByRole("button", { name: "Incorrect" })).toBeVisible();
  const posted = page.waitForResponse(
    (res) =>
      res.url().includes("/feedback") && res.request().method() === "POST",
  );
  await helpful.click();
  expect((await posted).status()).toBe(201);

  // The notes list on the profile shows it, and deleting it removes it.
  await open(page, "/student/me");
  const rows = page.locator(".notes-list li");
  await expect(rows).toHaveCount(notesBefore.length + 1, { timeout: 30_000 });
  await rows.first().getByRole("button").click();
  await expect
    .poll(async () =>
      (
        (await (
          await page.request.get("/api/notes", { headers })
        ).json()) as unknown[]
      ).length,
    )
    .toBe(notesBefore.length);
  await expect(rows).toHaveCount(notesBefore.length);

  // Admin triage shows the rating, reporter identity withheld.
  await signOut(page);
  await signIn(page, ADMIN);
  const queue = await apiGet<{
    rows: { rating: number; role: string; message_id: number | null }[];
    open_count: number;
  }>(page, "/admin/feedback?status=open&limit=20&offset=0");
  const rated = queue.rows.find((r) => r.rating === 1 && r.role === "student");
  expect(rated, "the Helpful rating is not in the triage queue").toBeTruthy();
  expect(rated!.message_id).not.toBeNull();
  const triageCard = page
    .locator("div.card")
    .filter({ has: page.getByRole("heading", { name: "Feedback triage" }) })
    .first();
  await expect(triageCard.locator("table.data tbody tr").first()).toBeVisible({
    timeout: 30_000,
  });
});

test("STU-14 AI memory view, edit, disable, and the next ask still works", async ({
  page,
}) => {
  await signIn(page, STUDENT);
  await open(page, "/student/me");

  const panel = page.locator(".card-ai");
  await expect(panel).toBeVisible();
  const memorySwitch = panel.getByRole("switch", {
    name: "What the tutor remembers about you",
  });
  await expect(memorySwitch).toHaveAttribute("aria-checked", "true");

  // Edit the learning preferences and persist them.
  await page.locator("#expstyle").selectOption("simple");
  await page.locator("#subjfocus").fill("science");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("p.ok")).toHaveText("Saved");
  const prefs = await apiGet<{
    memory_enabled: boolean;
    learning_prefs: { explanation_style: string; subject_focus: string };
  }>(page, "/students/me/prefs");
  expect(prefs.learning_prefs.explanation_style).toBe("simple");
  expect(prefs.learning_prefs.subject_focus).toBe("science");

  // Reload: the edit survives, it is not just component state.
  await open(page, "/student/me");
  await expect(page.locator("#expstyle")).toHaveValue("simple");
  await expect(page.locator("#subjfocus")).toHaveValue("science");

  // Disable memory, save, and read it back from the API.
  await page
    .locator(".card-ai")
    .getByRole("switch", { name: "What the tutor remembers about you" })
    .click();
  await expect(
    page
      .locator(".card-ai")
      .getByRole("switch", { name: "What the tutor remembers about you" }),
  ).toHaveAttribute("aria-checked", "false");
  await page.getByRole("button", { name: "Save" }).click();
  await expect
    .poll(
      async () =>
        (await apiGet<{ memory_enabled: boolean }>(page, "/students/me/prefs"))
          .memory_enabled,
    )
    .toBe(false);
  await expect(page.locator(".card-ai")).toContainText("Off");

  // A later ask still produces a grounded answer with memory off. What the
  // provider receives is API-owned (routers/common.py memory builder), so the
  // answer TEXT cannot be compared under LLM_PROVIDER=mock.
  await open(page, "/student/tutor");
  await askAndAwaitAnswer(page, QUESTION);

  // Restore, so this test leaves the shared seeded account as it found it.
  await open(page, "/student/me");
  await page
    .locator(".card-ai")
    .getByRole("switch", { name: "What the tutor remembers about you" })
    .click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect
    .poll(
      async () =>
        (await apiGet<{ memory_enabled: boolean }>(page, "/students/me/prefs"))
          .memory_enabled,
    )
    .toBe(true);
});

test("STU-03 history persists across reload and re-login, and New chat clears it", async ({
  page,
}) => {
  await signIn(page, STUDENT);
  await open(page, "/student/tutor");
  await askAndAwaitAnswer(page, QUESTION);

  // Reload: the conversation is server-side, so the chip is there and reopens
  // with both turns intact.
  await open(page, "/student/tutor");
  const chip = page.locator(".conv-chip button.conv-open").first();
  await expect(chip).toBeVisible({ timeout: 30_000 });
  await chip.click();
  await expect(page.locator(".bubble.assistant").first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.locator(".bubble.user").first()).toContainText("কোষ");

  // Re-login: still there.
  await signOut(page);
  await signIn(page, STUDENT);
  await open(page, "/student/tutor");
  const chip2 = page.locator(".conv-chip button.conv-open").first();
  await expect(chip2).toBeVisible({ timeout: 30_000 });
  await chip2.click();
  await expect(page.locator(".bubble.assistant").first()).toBeVisible({
    timeout: 30_000,
  });

  // New chat: the transcript is empty (no earlier turn leaks into it).
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.locator(".bubble")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator(".empty-title")).toBeVisible();
});
