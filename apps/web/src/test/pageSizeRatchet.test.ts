/**
 * F-094 (FE-03): eight page components exceeded the 500-line review budget the
 * audit set (AITutorPage was the first one split; its sections live under
 * pages/student/tutor/ now, LearnPage's reader and workspace tabs under
 * pages/student/learn/). QuizPage (832 -> 488) and AdminDashboard (797 -> 337)
 * were split in the wave-2 close-out: QuizPage's screens and panels live under
 * pages/student/quiz/, AdminDashboard's cards under components/admin/. The
 * remaining four over the budget (MePage 793, CreatePage 704, ClassesPage 685,
 * AssessmentsPage 623) are each a body of work that belongs in its own
 * reviewed change, so this is the ratchet that keeps the queue from growing
 * while they land: every page is capped at the size it has today, a file that
 * is split MUST lower its ceiling in the same change, and a page added from
 * now on must fit the 500-line budget outright.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const PAGES = join(process.cwd(), "src", "pages");
const BUDGET = 500;

/**
 * Recorded ceilings: lower on split. A raise is recorded only when the growth
 * is a required fix whose commit justifies it (the same rule the complexity
 * ratchet in ci.yml applies to its budget), so every increase is deliberate
 * and reviewed rather than drift.
 */
const CEILING: Record<string, number> = {
  "AdminDashboard.tsx": 337,
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
  "student/LearnPage.tsx": 306,
  "student/MePage.tsx": 793,
  "student/QuizPage.tsx": 488,
  "student/learn/ChapterAsk.tsx": 90,
  "student/learn/ChapterPractice.tsx": 174,
  "student/learn/LearnChapterPage.tsx": 481,
  "student/quiz/AssignedPanel.tsx": 119,
  "student/quiz/QuizResultScreen.tsx": 105,
  "student/quiz/QuizRunner.tsx": 132,
  "student/quiz/ReteachCards.tsx": 28,
  "student/quiz/RevisionPanel.tsx": 50,
  "student/quiz/StartQuizCard.tsx": 89,
  "student/tutor/AssistantContent.tsx": 40,
  "student/tutor/EvidenceModal.tsx": 33,
  // 189: 8f80e93 added the CodeQL mime allowlist to the preview data URL
  // (5 lines), e7e5268 formatted the file (2 lines) - the security fix and its
  // formatting are the recorded raise.
  "student/tutor/TutorComposer.tsx": 189,
  "student/tutor/TutorHistory.tsx": 126,
  // 269: eec2f6a namespaced the streaming-placeholder React keys with the
  // why-comment the fix requires.
  "student/tutor/TutorThread.tsx": 269,
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
      .filter(
        (key) => countLines(readFileSync(join(PAGES, key), "utf8")) > BUDGET,
      );
    expect(
      unrecorded,
      `new pages over ${BUDGET} lines (split before adding a ceiling):\n${unrecorded.join("\n")}`,
    ).toEqual([]);
  });
});
