/**
 * F-024: switching the selected child kept rendering the previous child's
 * name and scores until the new request resolved, and a failed fetch
 * silently removed the card entirely. The child sections are now keyed by
 * the child and fall back to explicit loading/error states.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ParentDashboard from "../pages/ParentDashboard";
import { t } from "../i18n";
import type { StudentBrief, StudentProgress } from "../types";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  getParentReport: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
}));

const CHILDREN: StudentBrief[] = [
  {
    student_id: 1,
    name: "Child A",
    class_level: 6,
    attempts_graded: 3,
    avg_score_pct: 80,
  },
  {
    student_id: 2,
    name: "Child B",
    class_level: 7,
    attempts_graded: 2,
    avg_score_pct: 60,
  },
];

const progressFor = (id: number, name: string): StudentProgress => ({
  student: { id, name, class_level: 6 },
  attempts_graded: id,
  avg_score_pct: 50 + id,
  by_chapter: [],
  weak_chapters: [],
});

const reportFor = (id: number, name: string) => ({
  student_id: id,
  name,
  class_level: 6,
  period: "weekly",
  window_start: "2026-01-01",
  window_end: "2026-01-07",
  quizzes_taken: 2,
  quizzes_graded: 2,
  avg_score_pct: 70,
  chapters_read: 1,
  chapters_completed: 1,
  questions_asked: 3,
  weak_chapters: [],
  strengths: [],
  suggestion_code: "reportSuggestion",
  suggestion_params: {},
});

const ACTIVITY = {
  days: [],
  streak: 1,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ParentDashboard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/parents/me/children") return Promise.resolve(CHILDREN);
    if (path === "/parents/me/children/1/progress")
      return Promise.resolve(progressFor(1, "Child A"));
    if (path === "/parents/me/children/2/progress")
      return Promise.resolve(progressFor(2, "Child B"));
    if (path.endsWith("/activity")) return Promise.resolve(ACTIVITY);
    return Promise.resolve(null);
  });
  apiMock.getParentReport.mockImplementation((id: number) =>
    Promise.resolve(reportFor(id, id === 1 ? "Child A" : "Child B")),
  );
});

describe("parent dashboard child switching (F-024)", () => {
  it("shows a loading state for the newly selected child, never the old data", async () => {
    const user = userEvent.setup();
    let releaseB!: (v: unknown) => void;
    const progressB = new Promise((resolve) => {
      releaseB = resolve;
    });
    apiMock.get.mockImplementation((path: string) => {
      if (path === "/parents/me/children") return Promise.resolve(CHILDREN);
      if (path === "/parents/me/children/1/progress")
        return Promise.resolve(progressFor(1, "Child A"));
      if (path === "/parents/me/children/2/progress") return progressB;
      if (path.endsWith("/activity")) return Promise.resolve(ACTIVITY);
      return Promise.resolve(null);
    });

    renderPage();
    const progressButtons = async () =>
      screen.findAllByRole("button", { name: t("progressTitle") });
    await screen.findByText("Child A");

    // Select child A and wait for its card.
    await user.click((await progressButtons())[0]);
    expect(
      await screen.findByText(`${t("progressTitle")} — Child A`),
    ).toBeInTheDocument();

    // Switch to child B: A's name must disappear immediately and a loading
    // state must take its place (pre-fix, A's card stayed until B resolved).
    await user.click((await progressButtons())[1]);
    const loadingCard = await screen.findByRole("region", {
      name: t("progressTitle"),
    });
    expect(within(loadingCard).getByRole("status")).toHaveTextContent(
      t("loading"),
    );
    expect(screen.queryByText(`${t("progressTitle")} — Child A`)).toBeNull();

    // Resolve B: now B's data shows.
    releaseB(progressFor(2, "Child B"));
    expect(
      await screen.findByText(`${t("progressTitle")} — Child B`),
    ).toBeInTheDocument();
    expect(screen.queryByText(`${t("progressTitle")} — Child A`)).toBeNull();
  });

  it("shows a retryable error instead of silently removing the card", async () => {
    const user = userEvent.setup();
    apiMock.get.mockImplementation((path: string) => {
      if (path === "/parents/me/children") return Promise.resolve(CHILDREN);
      return Promise.reject(new Error("down"));
    });
    apiMock.getParentReport.mockRejectedValue(new Error("down"));

    renderPage();
    await screen.findByText("Child A");
    await user.click(
      (await screen.findAllByRole("button", { name: t("progressTitle") }))[0],
    );

    // Pre-fix the failing progress/report requests just made the cards vanish.
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.length).toBeGreaterThan(0);
    expect(alerts[0]).toHaveTextContent(t("errorGeneric"));
    expect(
      screen.getAllByRole("button", { name: t("retry") }).length,
    ).toBeGreaterThan(0);
  });
});

// FE-FIX (numerals, a11y, duplication): the child table printed the class
// level and every score in Latin digits inside Bangla copy; a null average
// rendered as "–%" (a dash wearing a percent sign); the period control was a
// hand-rolled chip row with no aria-pressed where the shared Segmented
// primitive exists; and the heatmap was a second, drifting copy of the
// student's grid.
describe("parent dashboard numerals and controls", () => {
  it("renders quantities in the language's digits and never a bare dash with a unit", async () => {
    const user = userEvent.setup();
    apiMock.get.mockImplementation((path: string) => {
      if (path === "/parents/me/children")
        return Promise.resolve([
          { ...CHILDREN[0], avg_score_pct: null },
          CHILDREN[1],
        ]);
      if (path.endsWith("/progress"))
        return Promise.resolve({
          ...progressFor(1, "Child A"),
          avg_score_pct: null,
          by_chapter: [
            {
              chapter: "কোষ",
              asked: 4,
              correct: 3,
              accuracy: 75,
            },
          ],
        });
      if (path.endsWith("/activity"))
        return Promise.resolve({
          ...ACTIVITY,
          days: [{ date: "2026-11-10", questions: 2, quizzes: 1, minutes: 5 }],
        });
      return Promise.resolve(null);
    });

    renderPage();
    await screen.findByText("Child A");

    // Class levels are quantities: ৬ and ৭, not 6 and 7.
    expect(screen.getByText("৬")).toBeInTheDocument();
    expect(screen.getByText("৭")).toBeInTheDocument();

    // A null average is "—" and nothing more: no invented unit.
    await user.click(
      (await screen.findAllByRole("button", { name: t("progressTitle") }))[0],
    );
    await screen.findByText(`${t("progressTitle")} — Child A`);
    expect(screen.queryByText("—%")).toBeNull();

    // The per-chapter table and the report tiles follow the same policy.
    expect(await screen.findByText("৭৫%")).toBeInTheDocument();
    expect(
      await screen.findByText(t("reportQuizzesGraded")),
    ).toBeInTheDocument();
    expect(screen.getAllByText("২").length).toBeGreaterThan(0);
  });

  it("uses the labelled period group with a pressed state", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Child A");
    await user.click(
      (await screen.findAllByRole("button", { name: t("progressTitle") }))[0],
    );
    await screen.findByText(`${t("progressTitle")} — Child A`);

    const weekly = await screen.findByRole("button", {
      name: t("periodWeekly"),
    });
    expect(weekly).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: t("periodMonthly") }),
    ).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: t("periodMonthly") }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: t("periodMonthly") }),
      ).toHaveAttribute("aria-pressed", "true"),
    );
    // Same grid component as the student's own page, with its labelled image
    // equivalent intact (the fixture has an empty day list).
    expect(
      screen.getByRole("img", {
        name: t("heatmapSummary", {
          questions: 0,
          active: 0,
          days: ACTIVITY.days.length,
        }),
      }),
    ).toBeTruthy();
  });
});
