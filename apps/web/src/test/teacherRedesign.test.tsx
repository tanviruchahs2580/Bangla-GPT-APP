/** WP-DR: teacher shell split — Home, Classes student detail, Assessments
 *  papers library and Analytics classroom intelligence coverage. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TeacherHomePage from "../pages/teacher/TeacherHomePage";
import ClassesPage from "../pages/teacher/ClassesPage";
import AssessmentsPage from "../pages/teacher/AssessmentsPage";
import AnalyticsPage from "../pages/teacher/AnalyticsPage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  getTeacherWorkload: vi.fn(),
}));

vi.mock("../api", () => ({
  ...apiMock,
  apiBase: "/api",
  getToken: () => "tok",
}));

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

vi.mock("../AuthContext", () => authMock);

const me = {
  user_id: 2,
  email: "t@x.com",
  role: "teacher",
  profile_id: null,
  name: "Karima Begum",
  class_level: null,
};

const ROOMS = [
  { id: 1, class_level: 6, section: "GEN", student_count: 2 },
  { id: 2, class_level: 7, section: "GREEN", student_count: 1 },
];

const ROSTER = [
  {
    student_id: 11,
    name: "Rahim",
    class_level: 6,
    email: "rahim@school.edu",
    invite_pending: false,
    attempts_graded: 2,
    avg_score_pct: 72,
  },
  {
    student_id: 12,
    name: "Karim",
    class_level: 6,
    email: null,
    invite_pending: false,
    attempts_graded: 1,
    avg_score_pct: 28,
  },
];

const MATRIX = {
  class_level: 6,
  concepts: ["বল"],
  students: [
    {
      student_id: 12,
      name: "Karim",
      avg_score_pct: 28,
      attempts_graded: 1,
      trend: "down" as const,
      at_risk: true,
      weak_concepts: ["বল"],
      cells: { বল: { asked: 2, correct: 0, accuracy: 0, read: true } },
    },
  ],
};

const ANALYTICS = {
  class_level: 6,
  students: 2,
  chapters: [{ chapter: "কোষ", asked: 5, correct: 2, accuracy: 40 }],
  weak_chapters: ["কোষ"],
  students_detail: [],
};

const QP = {
  id: 1,
  class_level: 6,
  subject: "science",
  exam_type: "Test",
  marks: 10,
  duration_min: 10,
  difficulty: { easy: 30, medium: 50, hard: 20 },
  chapters: ["কোষ"],
  status: "draft",
  questions: [
    {
      ref: "q1",
      text: "TEXT q1",
      options: ["a", "b", "c", "d"],
      answer_index: 0,
      marks: 1,
      difficulty: "easy",
      chapter: "কোষ",
      reviewed: true,
    },
  ],
  meta: {},
  reviewed_at: null,
  finalized_at: null,
  created_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
  apiMock.getTeacherWorkload.mockResolvedValue({
    counts: {},
    minutes_saved: {},
    total_minutes_saved: 25,
    estimate: true,
    methodology: "heuristic",
  });
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/teacher/classrooms")
      return Promise.resolve(structuredClone(ROOMS));
    if (path.endsWith("/roster"))
      return Promise.resolve(structuredClone(ROSTER));
    if (path.includes("/analytics"))
      return Promise.resolve(structuredClone(ANALYTICS));
    if (path.includes("weak-matrix"))
      return Promise.resolve(structuredClone(MATRIX));
    if (path === "/teacher/support-plans") return Promise.resolve([]);
    if (path === "/teacher/assignments") return Promise.resolve([]);
    if (path === "/teacher/qpapers")
      return Promise.resolve([structuredClone(QP)]);
    if (path === "/teacher/curriculum-coverage")
      return Promise.resolve({ subjects: [], cells: [] });
    return Promise.resolve(null);
  });
  apiMock.post.mockResolvedValue({
    id: 5,
    student_id: 12,
    teacher_id: 1,
    class_level: 6,
    focus_concepts: ["বল"],
    plan: {
      weeks: [
        {
          week: 1,
          stage: "concept",
          concepts: ["বল"],
          action: "read",
          detail: "",
        },
      ],
    },
    created_at: null,
  });
});

function renderAt(ui: React.ReactElement, path: string, route: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WP-DR teacher home", () => {
  it("shows greeting stats, quick-create links and the AI insight", async () => {
    renderAt(<TeacherHomePage />, "/teacher", "/teacher");

    expect(
      await screen.findByText(t("thGreeting", { name: "Karima" })),
    ).toBeInTheDocument();
    expect(screen.getByText(t("students"))).toBeInTheDocument();
    expect(screen.getByText(t("thClassesStat"))).toBeInTheDocument();
    expect(screen.getByText(t("thDraftsStat"))).toBeInTheDocument();

    const qc = screen.getByRole("list", { name: undefined });
    expect(qc).toBeInTheDocument();

    // insight: one at-risk student via the weak matrix
    await waitFor(() =>
      expect(
        screen.getByText(t("thInsightRisk", { n: 1 }).replace("1", "1")),
      ).toBeInTheDocument(),
    );
    // workload-saved stays an explicit estimate
    await waitFor(() =>
      expect(screen.getByText(t("thWorkloadTitle"))).toBeInTheDocument(),
    );
    expect(screen.getByText("25")).toBeInTheDocument();
  });
});

describe("WP-DR classes student view", () => {
  it("opens a student detail with mastery, weak concepts and support plan", async () => {
    const user = userEvent.setup();
    renderAt(<ClassesPage />, "/teacher/classes", "/teacher/classes");

    // search narrows the roster
    await screen.findByText("Rahim");
    await user.type(screen.getByLabelText(t("clsSearchStudent")), "kar");
    await waitFor(() =>
      expect(screen.queryByText("Rahim")).not.toBeInTheDocument(),
    );

    // open Karim's detail
    await user.click(screen.getByRole("button", { name: t("cOpen") }));
    expect(await screen.findByText(t("clsStudentTitle"))).toBeInTheDocument();
    expect(screen.getByText(t("clsWeakConcepts"))).toBeInTheDocument();
    expect(screen.getByText("বল")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: t("spCreate") }));
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/teacher/support-plans", {
        student_id: 12,
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByText(new RegExp(t("spWeek", { n: 1 }))),
      ).toBeInTheDocument(),
    );
  });
});

describe("WP-DR assessments papers tab", () => {
  it("lists saved papers and opens the review workbench", async () => {
    const user = userEvent.setup();
    renderAt(
      <AssessmentsPage />,
      "/teacher/assessments",
      "/teacher/assessments?tab=papers",
    );

    await screen.findByText(/Test/);
    expect(screen.getByText(t("qpNeedsReview"))).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: t("cOpen") }));
    expect(await screen.findByText(t("stepDraft"))).toBeInTheDocument();
    expect(
      screen.getByText(t("qpReviewProgress", { done: 1, total: 1 })),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("qpFinalize") })).toBeEnabled();
  });
});

describe("WP-DR analytics classroom intelligence", () => {
  it("combines weak matrix + coverage into one top recommendation", async () => {
    renderAt(<AnalyticsPage />, "/teacher/analytics", "/teacher/analytics");

    expect(await screen.findByText(t("anaCiTop") + ":")).toBeInTheDocument();
    expect(screen.getByText(t("anaCiRisk", { n: 1 }))).toBeInTheDocument();
    // capacity framing, never replacement
    expect(screen.getByText(t("anaCapacityHint"))).toBeInTheDocument();
  });
});
