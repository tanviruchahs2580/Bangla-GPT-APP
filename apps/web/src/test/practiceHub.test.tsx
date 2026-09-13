/** WP-DR: the Practice hub replaces the four-tab quiz page — a prominent
 *  weak-area block on top, and teacher-assigned work merged into one list. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import QuizPage from "../pages/student/QuizPage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

const me = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "S",
  class_level: 6,
};

const PROGRESS = {
  student: {},
  attempts_graded: 3,
  avg_score_pct: 48,
  by_chapter: [],
  weak_chapters: ["কোষ", "বল"],
};

const DASHBOARD = {
  user: me,
  today: "2026-09-13",
  continue_learning: null,
  quick_actions: [],
  recommendation: {
    type: "weak_chapter",
    subject: "science",
    chapter: "কোষ",
    reason: null,
  },
  progress: null,
};

const SHORT_TEST_MINE = [
  {
    id: 3,
    classroom_id: 1,
    attempt_id: 33,
    subject: "science",
    chapter: "বল",
    num_questions: 5,
    duration_min: 10,
    questions: [{ id: "q", question_text: "?", options: ["a", "b"] }],
    created_at: null,
    expires_at: null,
    expired: false,
  },
];

const ASSIGNMENT_MINE = [
  {
    id: 9,
    attempt_id: 44,
    subject: "science",
    chapter: "আলো",
    questions: [{ id: "q2", question_text: "?", options: ["a", "b"] }],
    due_at: "2026-09-20T10:00:00",
    overdue: false,
    done: true,
  },
];

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <QuizPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WP-DR practice hub", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    apiMock.get.mockImplementation((path: string) => {
      if (path.endsWith("/progress"))
        return Promise.resolve(structuredClone(PROGRESS));
      if (path === "/dashboard/summary")
        return Promise.resolve(structuredClone(DASHBOARD));
      if (path === "/revision/due")
        return Promise.resolve({ today: "", due_count: 0, items: [] });
      if (path === "/shorttests/mine")
        return Promise.resolve(structuredClone(SHORT_TEST_MINE));
      if (path === "/assignments/mine")
        return Promise.resolve(structuredClone(ASSIGNMENT_MINE));
      return Promise.resolve(null);
    });
    apiMock.post.mockResolvedValue({
      attempt_id: 1,
      requested: 3,
      questions: [{ id: "q1", question_text: "?", options: ["a", "b"] }],
    });
  });

  it("starts a weak-chapter quiz from the recommendation and shows weak chips", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText(t("weakPracticeTitle"))).toBeInTheDocument();
    // weak chips come from the progress query — await the async resolve
    expect(await screen.findByText("কোষ")).toBeInTheDocument();

    // weak block appears before the tab list in DOM order (most prominent)
    const main = document.querySelector("main.shell-main")!;
    const tabIndex = Array.from(main.querySelectorAll('[role="tablist"]')).map(
      (el) => Array.from(main.children).indexOf(el.closest("main > *")!),
    );

    const startBtn = screen.getByRole("button", {
      name: new RegExp(t("weakPracticeStart")),
    });
    expect(
      Array.from(main.children).indexOf(startBtn.closest("main > *")!),
    ).toBeLessThan(Math.max(...tabIndex));

    await user.click(startBtn);
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        "/quizzes",
        expect.objectContaining({
          subject: "science",
          chapter: "কোষ",
          num_questions: 3,
        }),
      ),
    );
  });

  it("merges teacher-assigned short tests and bulk assignments into one list", async () => {
    const user = userEvent.setup();
    renderPage();

    const tab = await screen.findByRole("tab", {
      name: new RegExp(t("teacherAssignedTab")),
    });
    await waitFor(() => expect(tab).toHaveTextContent("2"));
    await user.click(tab);

    // the chapter name also shows as a weak chip above, so match all
    expect((await screen.findAllByText("বল")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("আলো").length).toBeGreaterThan(0);
    // both kinds are labeled inside the merged list
    expect(screen.getByText(t("assignedShortTest"))).toBeInTheDocument();
    expect(screen.getByText(t("assignedBulk"))).toBeInTheDocument();
  });
});
