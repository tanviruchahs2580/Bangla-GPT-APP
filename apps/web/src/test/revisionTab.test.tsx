import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import QuizPage from "../pages/student/QuizPage";
import { t } from "../i18n";
import type { RevisionDue } from "../types";

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
  class_level: 6,
};

const DUE: RevisionDue = {
  today: "2026-01-05",
  due_count: 1,
  items: [
    {
      id: 11,
      question: "Koshe ki prosno?",
      options: ["Option-A", "Option-B"],
      correct_index: 1,
      chapter: "Kosh-Chapter",
      reps: 0,
      interval_days: 0,
      ease_factor: 2.5,
      due_date: "2026-01-05",
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

describe("S1.10 revision tab UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    apiMock.get.mockImplementation((path: string) => {
      if (path === "/revision/due")
        return Promise.resolve(structuredClone(DUE));
      if (path.includes("/progress"))
        return Promise.resolve({
          student: {},
          attempts_graded: 0,
          avg_score_pct: null,
          by_chapter: [],
          weak_chapters: [],
        });
      return Promise.resolve(null);
    });
    apiMock.post.mockResolvedValue({
      id: 11,
      reps: 1,
      interval_days: 1,
      due_date: "2026-01-06",
    });
  });

  it("shows the due count badge and the revision card after switching tabs", async () => {
    const user = userEvent.setup();
    renderPage();

    const tab = await screen.findByRole("tab", {
      name: new RegExp(t("revisionTab")),
    });
    await waitFor(() => expect(tab).toHaveTextContent("1"));

    await user.click(tab);
    expect(await screen.findByText("Koshe ki prosno?")).toBeInTheDocument();
    expect(screen.getByText("Option-A")).toBeInTheDocument();
  });

  it("answering a due item POSTs the review and refreshes the list", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("tab", { name: new RegExp(t("revisionTab")) }),
    );
    await user.click(await screen.findByText("Option-B"));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/revision/11/review", {
        chosen: 1,
      }),
    );
    // refetch of the due list happened after the review
    await waitFor(() => {
      const calls = apiMock.get.mock.calls.filter(
        (c: unknown[]) => c[0] === "/revision/due",
      );
      expect(calls.length).toBeGreaterThanOrEqual(2);
    });
  });
});
