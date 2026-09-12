// S4.5: re-teach cards must show before the first question of a new quiz and
// on the result screen when wrong answers opened a KG gap.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import QuizPage from "../pages/student/QuizPage";
import { t } from "../i18n";
import type { QuizResult, QuizStarted, ReteachCard } from "../types";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
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
  class_level: 7,
};

const CARD: ReteachCard = {
  concept: "Kosh-Concept",
  prereq: "Kosh-Prereq",
  depth: 1,
  excerpt: "Kosh excerpt sentence from the textbook.",
};

const STARTED: QuizStarted = {
  attempt_id: 91,
  requested: 1,
  reteach: [CARD],
  questions: [
    {
      id: "q1",
      question_text: "Koshe ki? Question-One?",
      options: ["Ans-A", "Ans-B"],
    },
  ],
};

const RESULT: QuizResult = {
  attempt_id: 91,
  score_pct: 0,
  correct: 0,
  total: 1,
  reteach: [CARD],
  review: [
    {
      question_text: "Koshe ki? Question-One?",
      options: ["Ans-A", "Ans-B"],
      chosen: 0,
      correct_index: 1,
      is_correct: false,
      chapter: "Kosh-Chapter",
    },
  ],
};

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

describe("S4.5 re-teach cards in the quiz flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    apiMock.get.mockImplementation((path: string) => {
      if (path === "/revision/due")
        return Promise.resolve({
          today: "2026-01-05",
          due_count: 0,
          items: [],
        });
      if (path.includes("/progress"))
        return Promise.resolve({
          student: {},
          attempts_graded: 0,
          avg_score_pct: null,
          by_chapter: [],
          weak_chapters: [],
        });
      return Promise.resolve([]);
    });
  });

  it("shows the grounded re-teach card before the first question of a new quiz", async () => {
    apiMock.post.mockImplementation((path: string) => {
      if (path === "/quizzes") return Promise.resolve(structuredClone(STARTED));
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: new RegExp(t("startQuiz")) }),
    );
    expect(await screen.findByText(t("reteachTitle"))).toBeInTheDocument();
    expect(screen.getByText(/Kosh-Prereq/)).toBeInTheDocument();
    expect(screen.getByText(CARD.excerpt)).toBeInTheDocument();
    // the question is still playable underneath the card
    expect(screen.getByText(/Question-One?/)).toBeInTheDocument();
  });

  it("shows re-teach cards on the result screen after a wrong answer", async () => {
    apiMock.post.mockImplementation((path: string) => {
      if (path === "/quizzes")
        return Promise.resolve({ ...structuredClone(STARTED), reteach: [] });
      if (path.endsWith("/submit"))
        return Promise.resolve(structuredClone(RESULT));
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: new RegExp(t("startQuiz")) }),
    );
    await screen.findByText(/Question-One?/);
    await user.click(screen.getByRole("button", { name: "Ans-A" }));
    await user.click(
      await screen.findByRole("button", { name: new RegExp(t("finishQuiz")) }),
    );

    await waitFor(() =>
      expect(screen.getByText(t("reteachTitle"))).toBeInTheDocument(),
    );
    expect(screen.getByText(CARD.excerpt)).toBeInTheDocument();
    expect(screen.getByText(/Kosh-Concept/)).toBeInTheDocument();
  });

  it("renders nothing when the API returns no gaps (no regressions for fresh students)", async () => {
    apiMock.post.mockImplementation((path: string) => {
      if (path === "/quizzes")
        return Promise.resolve({ ...structuredClone(STARTED), reteach: [] });
      if (path.endsWith("/submit"))
        return Promise.resolve({ ...structuredClone(RESULT), reteach: [] });
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: new RegExp(t("startQuiz")) }),
    );
    await screen.findByText(/Question-One?/);
    expect(screen.queryByText(t("reteachTitle"))).not.toBeInTheDocument();
  });
});
