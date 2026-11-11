/**
 * FE-FIX-002: the practice hub ignores its query errors.
 *
 * With `progress` failing, the weak-spot card rendered "এখনো কোনো দুর্বল অধ্যায়
 * নেই" — a claim about the student's own work, derived from a request that
 * never answered — and with `dashboard` failing the personalised practice
 * button simply vanished, so the one action the page exists for disappeared
 * with no explanation and no way to retry it.
 *
 * FE-FIX-012 rides in the same file: the same hub posts the graded attempt, and
 * "Finish" had no synchronous double-submit guard (only `busy`, which lands a
 * render late). Two clicks dispatched in one act block post the attempt twice;
 * the second POST hits an already-graded attempt and the student is told their
 * submitted quiz failed.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import QuizPage from "../pages/student/QuizPage";
import { setLang, t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

const STUDENT = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "S",
  class_level: 6,
};

function renderHub() {
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

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  authMock.useAuth.mockReturnValue({ me: STUDENT, signOut: vi.fn() });
  apiMock.get.mockImplementation((url: string) => {
    if (url.startsWith("/revision/due"))
      return Promise.resolve({ due_count: 0, items: [] });
    return Promise.resolve([]);
  });
});

describe("practice hub failure states", () => {
  it("says the weak-chapter data could not be read, and retries it", async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url.startsWith("/students/7/progress"))
        return Promise.reject(new Error("503"));
      if (url.startsWith("/dashboard/summary"))
        return Promise.resolve({ recommendation: null });
      return Promise.resolve([]);
    });
    renderHub();

    expect(await screen.findByText(t("progressLoadFailed"))).toBeTruthy();
    expect(screen.queryByText(t("noWeakChapters"))).toBeNull();
    // The retry re-asks, and the card recovers.
    apiMock.get.mockImplementation((url: string) => {
      if (url.startsWith("/students/7/progress"))
        return Promise.resolve({
          attempts_graded: 0,
          avg_score_pct: null,
          weak_chapters: [],
          by_chapter: [],
        });
      if (url.startsWith("/dashboard/summary"))
        return Promise.resolve({ recommendation: null });
      return Promise.resolve([]);
    });
    fireEvent.click(screen.getByRole("button", { name: t("retry") }));
    expect(await screen.findByText(t("noWeakChapters"))).toBeTruthy();
  });

  it("explains the missing personalised button when the recommendation fails", async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url.startsWith("/students/7/progress"))
        return Promise.resolve({
          attempts_graded: 0,
          avg_score_pct: null,
          weak_chapters: ["কোষ"],
          by_chapter: [],
        });
      if (url.startsWith("/dashboard/summary"))
        return Promise.reject(new Error("503"));
      return Promise.resolve([]);
    });
    renderHub();

    expect(await screen.findByText(t("recommendationLoadFailed"))).toBeTruthy();
    // The button is absent because its data is, and the retry says so.
    expect(
      screen.queryByRole("button", { name: t("weakPracticeStart") }),
    ).toBeNull();
  });
});

describe("quiz submit double-submit guard", () => {
  it("posts the graded attempt once when Finish is fired twice in one tick", async () => {
    apiMock.post.mockImplementation((url: string) => {
      if (url === "/quizzes")
        return Promise.resolve({
          attempt_id: 42,
          requested: 1,
          questions: [
            {
              question_text: "Q1",
              options: ["a", "b", "c", "d"],
              correct_index: 0,
              chapter: "কোষ",
              concept: "c1",
            },
          ],
        });
      if (url === "/quizzes/42/submit")
        return Promise.resolve({
          attempt_id: 42,
          score_pct: 100,
          correct: 1,
          total: 1,
          review: [],
        });
      return Promise.resolve({});
    });
    renderHub();

    fireEvent.click(
      await screen.findByRole("button", { name: t("startQuiz") }),
    );
    const option = await screen.findByRole("radio", { name: /a/ });
    fireEvent.click(option);
    const finish = await screen.findByRole("button", {
      name: t("finishQuiz"),
    });

    // One act block: React has not flushed `busy` yet, so the button is still
    // clickable — only the synchronous ref can stop the second POST.
    await act(async () => {
      fireEvent.click(finish);
      fireEvent.click(finish);
    });

    await waitFor(() =>
      expect(
        apiMock.post.mock.calls.filter(([url]) =>
          String(url).endsWith("/submit"),
        ),
      ).toHaveLength(1),
    );
  });
});

// FE-FIX (numerals): the tab badges count work the student owes, so they carry
// the language's digits like every other quantity on the page.
describe("practice hub numeral policy", () => {
  it("prints the due and assigned counts in Bangla digits", async () => {
    setLang("bn");
    apiMock.get.mockImplementation((url: string) => {
      if (url.startsWith("/revision/due"))
        return Promise.resolve({ due_count: 4, items: [] });
      if (url.startsWith("/shorttests/mine"))
        return Promise.resolve([
          {
            id: 1,
            subject: "science",
            chapter: "কোষ",
            num_questions: 5,
            attempt_id: 11,
            expired: false,
            score_pct: null,
            created_at: "2026-11-01T10:00:00",
            questions: [],
          },
        ]);
      if (url.startsWith("/students/7/progress"))
        return Promise.resolve({
          attempts_graded: 0,
          avg_score_pct: null,
          weak_chapters: [],
          by_chapter: [],
        });
      if (url.startsWith("/dashboard/summary"))
        return Promise.resolve({ recommendation: null });
      return Promise.resolve([]);
    });
    renderHub();

    const tab = await screen.findByRole("tab", {
      name: new RegExp(t("revisionTab")),
    });
    // The badge lands when the due query resolves.
    await waitFor(() => expect(tab.textContent).toContain("৪"));
    const assignedTab = await screen.findByRole("tab", {
      name: new RegExp(t("teacherAssignedTab")),
    });
    await waitFor(() => expect(assignedTab.textContent).toContain("১"));
  });
});
