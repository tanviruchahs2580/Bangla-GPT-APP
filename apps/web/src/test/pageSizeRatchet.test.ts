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
 * E2 (2026-11-17, unified loading + empty states) raised eleven more, for
 * the same reason as the FE-FIX pass: each audited loader now renders the
 * surface's real shape as Skeleton rows (a Spinner keeps the loading state
 * announced, since the skeleton blocks are aria-hidden) and each text-only
 * empty state became the shared EmptyState primitive — branches and JSX
 * that did not exist before are the growth. Two touched pages stayed under
 * their recorded ceilings and keep them: ParentDashboard (391 ≤ 404) and
 * MePage (746 ≤ 793).
 *
 * Every entry is that file's measured count after the change. No page that was
 * split in a pass kept its old ceiling. The two that moved by one or two lines
 * when prettier reformatted them are re-measured, not re-justified: the
 * formatting is the change.
 */
const CEILING: Record<string, number> = {
  // 387: E1 (2026-11-17) moved the impersonation reason out of window.prompt
  // into the shared Modal — the dialog JSX, its target/reason state and the
  // preserved <3-chars guard are the growth. The interaction shell is the fix;
  // no authorization or tenancy logic moved.
  // 396: E2 (2026-11-17) gave the settled-empty users table the shared
  // EmptyState (the table keeps rendering while a request is in flight).
  "AdminDashboard.tsx": 401, // E3 2026-11-17: cardable data-labels + page-head (measured 401)
  // 191: Font A fidelity (2026-11-20) moved the page onto the design system:
  // the mode switch became the shared Segmented (it borrowed the 44px icon
  // button class and clipped both labels) and each control gained Field +
  // .input (they rendered as raw UA inputs). Wrapper JSX is the growth; no
  // branch, state or API call was added.
  "ForgotResetPage.tsx": 191,
  "LegalPage.tsx": 127,
  "LoginPage.tsx": 353,
  "MaintenancePage.tsx": 37,
  "NotFoundPage.tsx": 31,
  "ParentDashboard.tsx": 404,
  "RegisterPage.tsx": 288,
  // 147: E2 (2026-11-17) — the loading branch now renders the page's real
  // shape (stat grid, health card, at-risk rows) and the at-risk empty state
  // became the shared EmptyState.
  "SchoolDashboard.tsx": 162,
  "StatusPage.tsx": 160, // E2 (2026-11-17): shaped skeleton loading branch.
  "WelcomePage.tsx": 128,
  // 708: E1 (2026-11-17) replaced window.confirm with the shared
  // ConfirmDialog for chat deletion — the deleteTarget state and the dialog
  // render are the growth; the delete logic itself is unchanged.
  "student/AITutorPage.tsx": 713, // E6 2026-11-18: back-button dirty marker (measured 713)
  "student/HomePage.tsx": 342, // E2 (2026-11-17): shared Skeleton swap.
  "student/LearnPage.tsx": 382, // E2 (2026-11-17): shared Skeleton swap.
  "student/MePage.tsx": 793,
  "student/QuizPage.tsx": 593, // E6 2026-11-18: back-button dirty marker (measured 593)
  "student/learn/ChapterAsk.tsx": 121,
  "student/learn/ChapterPractice.tsx": 184,
  "student/learn/LearnChapterPage.tsx": 495, // E2 (2026-11-17): Skeleton swap.
  // 137: E2 (2026-11-17) — the loading card renders row skeletons (Spinner
  // keeps the announcement) and the empty list became the shared EmptyState.
  "student/quiz/AssignedPanel.tsx": 137,
  "student/quiz/QuizResultScreen.tsx": 111,
  "student/quiz/QuizRunner.tsx": 138,
  "student/quiz/ReteachCards.tsx": 28,
  // 89: E2 (2026-11-17) — same treatment as AssignedPanel: row skeletons
  // while the queue loads, shared EmptyState when it is empty.
  "student/quiz/RevisionPanel.tsx": 89,
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
  // 411: E2 (2026-11-17) — the workload card's loading branch renders the
  // stat's shape; the support-plan and workload empty states became the
  // shared EmptyState.
  "teacher/AnalyticsPage.tsx": 411,
  // 636: E2 (2026-11-17) — the four text-only list empty states (papers,
  // roster, bulk assignments, short tests) became the shared EmptyState.
  // 638: D (2026-11-18) — the roster and attempt-results tables moved onto
  // the shared ResponsiveTable; the declarative column objects are a couple
  // of lines more verbose per table while the repeated table markup they
  // replace now lives once in the component.
  "teacher/AssessmentsPage.tsx": 638,
  // 692: E2 (2026-11-17) — the no-classrooms and empty-roster empty states
  // became the shared EmptyState (the first moved out of the chip row).
  // 702: D (2026-11-18) — the roster table moved onto the shared
  // ResponsiveTable (same trade as AssessmentsPage above: the column
  // declarations cost lines here, the table markup is now shared).
  "teacher/ClassesPage.tsx": 702,
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
