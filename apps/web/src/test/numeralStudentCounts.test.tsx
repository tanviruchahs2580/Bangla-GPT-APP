/**
 * UX-009: the glossary's numeral policy (docs/glossary-bn.md) requires Bangla
 * digits for quantities a student reads, converted at the t() / formatNumber
 * boundary. These sites bypassed that boundary and printed `String(value)`,
 * so a Bengali screen showed "1/3" and a Latin "62%" next to Bangla ones.
 *
 * Covered here: the quiz progress badge and ring, the result ring, the home
 * snapshot's streak and the continue-learning class, and the four report
 * statistics on the Me page.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HomePage from "../pages/student/HomePage";
import MePage from "../pages/student/MePage";
import { QuizResultScreen } from "../pages/student/quiz/QuizResultScreen";
import { QuizRunner } from "../pages/student/quiz/QuizRunner";
import { formatNumber, setLang, t } from "../i18n";
import type { QuizResult, QuizStarted } from "../types";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  getMyReport: vi.fn(),
  apiBase: "/api",
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
}));
vi.mock("../AuthContext", () => authMock);

const me = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "Rahim Uddin",
  class_level: 6,
};

function wrap(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  setLang("bn");
  authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
});

afterEach(() => cleanup());

describe("quiz runner progress numerals", () => {
  const started: QuizStarted = {
    attempt_id: 1,
    requested: 3,
    questions: [
      { id: "q1", question_text: "প্রশ্ন এক", options: ["ক", "খ"] },
      { id: "q2", question_text: "প্রশ্ন দুই", options: ["ক", "খ"] },
      { id: "q3", question_text: "প্রশ্ন তিন", options: ["ক", "খ"] },
    ],
  };

  function renderRunner(current = 0, answers: Record<number, number> = {}) {
    return wrap(
      <QuizRunner
        started={started}
        current={current}
        answers={answers}
        busy={false}
        error={null}
        confirmSubmit={false}
        unanswered={3}
        onChoose={() => {}}
        onPrevious={() => {}}
        onNext={() => {}}
        onRequestSubmit={() => {}}
        onSubmitAnyway={() => {}}
        onKeepAnswering={() => {}}
      />,
    );
  }

  it("counts the question position and the answered total in Bangla", () => {
    renderRunner(2, { 0: 1, 1: 0 });

    // "question 3 of 3" in the header badge, "2 of 3 answered" in the ring.
    expect(screen.getByText(`৩/৩`)).toBeInTheDocument();
    expect(screen.getByText(`২/৩`)).toBeInTheDocument();
    expect(screen.queryByText("3/3")).toBeNull();
    expect(screen.queryByText("2/3")).toBeNull();
  });
});

describe("quiz result numerals", () => {
  const result: QuizResult = {
    attempt_id: 1,
    score_pct: 87.5,
    correct: 7,
    total: 8,
    review: [],
  };

  it("shows the score ring in Bangla digits", () => {
    wrap(
      <QuizResultScreen
        result={result}
        onExplain={() => {}}
        onRestart={() => {}}
      />,
    );

    // The ring's own label rounds to 88; the surrounding sentence comes from
    // t("correctOutOf") and already converts.
    expect(screen.getByText(`${formatNumber(88)}%`)).toBeInTheDocument();
    expect(screen.queryByText("88%")).toBeNull();
  });
});

describe("student home numerals", () => {
  it("renders the streak and the continue-learning class in Bangla", async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path.endsWith("/progress"))
        return Promise.resolve({
          student: {},
          attempts_graded: 4,
          avg_score_pct: 72,
          by_chapter: [],
          weak_chapters: [],
        });
      if (path.endsWith("/activity"))
        return Promise.resolve({ days: [], streak: 3, minutes_total: 40 });
      if (path === "/dashboard/summary")
        return Promise.resolve({
          user: me,
          today: "2026-09-13",
          continue_learning: {
            subject: "science",
            chapter: "কোষ",
            class_level: 6,
            excerpt: "কোষ হলো জীবদেহের একক",
          },
          quick_actions: [],
          recommendation: null,
          progress: null,
        });
      return Promise.resolve(null);
    });
    wrap(<HomePage />);

    const snapshot = (await screen.findByText(t("progressSnapshot"))).closest(
      ".card",
    ) as HTMLElement;
    // The streak figure itself, beside its already-Bangla label. The card
    // renders skeletons until the progress query lands, so wait on the value.
    expect(
      await within(snapshot).findByText(formatNumber(3)),
    ).toBeInTheDocument();
    expect(within(snapshot).queryByText("3")).toBeNull();

    const cont = (await screen.findByText(/শ্রেণি ৬/)).textContent ?? "";
    expect(cont).not.toContain("শ্রেণি 6");
  });
});

describe("me-page report numerals", () => {
  beforeEach(() => {
    apiMock.getMyReport.mockResolvedValue({
      student_id: 1,
      name: "S",
      class_level: 6,
      period: "weekly",
      window_start: "2026-10-10T00:00:00",
      window_end: "2026-10-16T00:00:00",
      quizzes_taken: 3,
      quizzes_graded: 3,
      avg_score_pct: 62.0,
      chapters_read: 2,
      chapters_completed: 1,
      questions_asked: 5,
      weak_chapters: [],
      strengths: [],
      suggestion_code: "sugg_general_support",
      suggestion_params: {},
    });
    apiMock.get.mockResolvedValue(null);
  });

  it("renders the four report statistics in Bangla", async () => {
    wrap(<MePage />);

    const report = (await screen.findByText(t("myReportTitle"))).closest(
      ".card",
    ) as HTMLElement;

    const stat = (label: string) =>
      within(report).getByText(label).parentElement as HTMLElement;

    expect(stat(t("reportQuizzesGraded"))).toHaveTextContent(formatNumber(3));
    expect(stat(t("reportAvg"))).toHaveTextContent(`${formatNumber(62)}%`);
    expect(stat(t("reportChaptersRead"))).toHaveTextContent(formatNumber(2));
    expect(stat(t("reportQuestions"))).toHaveTextContent(formatNumber(5));
  });
});
