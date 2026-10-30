/**
 * F-094 (FE-03): eight page components exceed the 500-line review budget the
 * audit set (AITutorPage was the first one split; its sections live under
 * pages/student/tutor/ now). The remaining seven are each a body of work that
 * belongs in its own reviewed change, so this is the ratchet that keeps the
 * queue from growing while they land: every page is capped at the size it has
 * today, a file that is split MUST lower its ceiling in the same change, and a
 * page added from now on must fit the 500-line budget outright.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const PAGES = join(process.cwd(), "src", "pages");
const BUDGET = 500;

/** Recorded ceilings: lower on split, never raise. */
const CEILING: Record<string, number> = {
  "AdminDashboard.tsx": 797,
  "ForgotResetPage.tsx": 185,
  "LegalPage.tsx": 127,
  "LoginPage.tsx": 353,
  "MaintenancePage.tsx": 37,
  "NotFoundPage.tsx": 31,
  "ParentDashboard.tsx": 404,
  "RegisterPage.tsx": 288,
  "SchoolDashboard.tsx": 137,
  "StatusPage.tsx": 100,
  "WelcomePage.tsx": 128,
  "student/AITutorPage.tsx": 625,
  "student/HomePage.tsx": 319,
  "student/LearnPage.tsx": 1023,
  "student/MePage.tsx": 793,
  "student/QuizPage.tsx": 832,
  "student/tutor/AssistantContent.tsx": 40,
  "student/tutor/EvidenceModal.tsx": 33,
  "student/tutor/TutorComposer.tsx": 179,
  "student/tutor/TutorHistory.tsx": 126,
  "student/tutor/TutorThread.tsx": 264,
  "teacher/AnalyticsPage.tsx": 384,
  "teacher/AssessmentsPage.tsx": 624,
  "teacher/ClassesPage.tsx": 688,
  "teacher/CreatePage.tsx": 706,
  "teacher/TeacherHomePage.tsx": 174,
  "teacher/TeacherProfilePage.tsx": 119,
};

/** `wc -l` semantics: the trailing newline does not open a new line. */
function countLines(text: string): number {
  return text.split("\n").length - 1;
}

function pageFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return pageFiles(path);
    return entry.name.endsWith(".tsx") ? [path] : [];
  });
}

describe("page size budget (F-094)", () => {
  const files = pageFiles(PAGES);

  it("every existing page stays within its recorded ceiling", () => {
    const over: string[] = [];
    for (const file of files) {
      const key = relative(PAGES, file).replace(/\\/g, "/");
      const ceiling = CEILING[key];
      expect(ceiling, `${key} has no ceiling recorded`).toBeDefined();
      const lines = countLines(readFileSync(file, "utf8"));
      if (lines > ceiling) over.push(`${key}: ${lines} > ${ceiling}`);
    }
    expect(over, `pages grew past their ceiling:\n${over.join("\n")}`).toEqual(
      [],
    );
  });

  it("a page added since the audit fits the 500-line budget outright", () => {
    const unrecorded = files
      .map((file) => relative(PAGES, file).replace(/\\/g, "/"))
      .filter((key) => CEILING[key] === undefined)
      .filter((key) => countLines(readFileSync(join(PAGES, key), "utf8")) > BUDGET);
    expect(
      unrecorded,
      `new pages over ${BUDGET} lines (split before adding a ceiling):\n${unrecorded.join("\n")}`,
    ).toEqual([]);
  });
});
