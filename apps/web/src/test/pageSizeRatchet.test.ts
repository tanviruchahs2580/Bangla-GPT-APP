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
 *
 * The UX-001..UX-009 pass (2026-11-10) grew the pages whose behaviour it
 * changed — a missing empty state, `role="alert"` on seven error lines, the
 * revision tab's loading/error branches, the workload card's request-state
 * branch, a single streaming bubble, one send/stop element and Bangla
 * numerals at the sites docs/glossary-bn.md names. Each ceiling below is that
 * file's measured count after the fix; AssessmentsPage shrank (the tablist
 * became the shared Segmented control) and its ceiling drops with it.
 *
 * The FE-FIX pass raised nine more, all in the same class and for the same
 * reason — here the fix *is* the extra lines, because each defect was a state
 * that was not rendered at all:
 *
 *   SchoolDashboard   a missing average was printed as a warning-toned 0%
 *                     (`avg_score_pct ?? 0`); it now says so honestly, and the
 *                     roster gained the pager its API already supported.
 *   StatusPage        the API's English component names and details were
 *                     rendered verbatim inside a Bangla UI; mapping them is a
 *                     table, and a table is lines.
 *   AITutorPage       an IME composition guard, a scroll that no longer fights
 *                     the reader mid-stream, the typed question kept on a
 *                     failed conversation create, and a synchronous
 *                     double-submit guard.
 *   HomePage          the same IME guard on the home composer.
 *   ChapterAsk        a labelled input and a live region for the answer.
 *   ChapterPractice   Bangla numerals at the recorded boundary.
 *   LearnChapterPage  bookmark rollback on failure, plus the numerals.
 *   LearnPage         a per-subject fetch failure no longer renders as a
 *                     zero-width ring; plus the numerals.
 *   QuizResultScreen  Bangla numerals.
 *
 * FE-FIX-019 (the consent gate's surface) accounts for the rest: QuizPage
 * carries the blocked state, maps the coded 403 in its three entry points and
 * passes the notice into the runner and the result screen, and the composer,
 * history and thread each gained a branch. TeacherHomePage gained the drafts
 * query in its error banner — the same class of fix, a state that was not
 * rendered.
 *
 * Every entry is that file's measured count after the change. No page that was
 * split in a pass kept its old ceiling. The two that moved by one or two lines
 * when prettier reformatted them are re-measured, not re-justified: the
 * formatting is the change.
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
  "SchoolDashboard.tsx": 147,
  "StatusPage.tsx": 148,
  "WelcomePage.tsx": 128,
  "student/AITutorPage.tsx": 688,
  "student/HomePage.tsx": 335,
  "student/LearnPage.tsx": 381,
  "student/MePage.tsx": 793,
  "student/QuizPage.tsx": 586,
  "student/learn/ChapterAsk.tsx": 121,
  "student/learn/ChapterPractice.tsx": 184,
  "student/learn/LearnChapterPage.tsx": 494,
  "student/quiz/AssignedPanel.tsx": 119,
  "student/quiz/QuizResultScreen.tsx": 111,
  "student/quiz/QuizRunner.tsx": 138,
  "student/quiz/ReteachCards.tsx": 28,
  "student/quiz/RevisionPanel.tsx": 77,
  "student/quiz/StartQuizCard.tsx": 100,
  "student/tutor/AssistantContent.tsx": 40,
  "student/tutor/EvidenceModal.tsx": 33,
  // 189: 8f80e93 added the CodeQL mime allowlist to the preview data URL
  // (5 lines), e7e5268 formatted the file (2 lines) - the security fix and its
  // formatting are the recorded raise.
  // 192: UX-002's role="alert" and UX-007's single send/stop element, whose
  // why-comments are part of the fix.
  "student/tutor/TutorComposer.tsx": 203,
  "student/tutor/TutorHistory.tsx": 130,
  // 269: eec2f6a namespaced the streaming-placeholder React keys with the
  // why-comment the fix requires.
  // 289: UX-006 moved the typing dots into the streaming bubble and gave the
  // placeholder its own condition, so only one assistant bubble is on screen.
  "student/tutor/TutorThread.tsx": 297,
  "teacher/AnalyticsPage.tsx": 395,
  "teacher/AssessmentsPage.tsx": 618,
  "teacher/ClassesPage.tsx": 688,
  "teacher/CreatePage.tsx": 706,
  "teacher/TeacherHomePage.tsx": 180,
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
