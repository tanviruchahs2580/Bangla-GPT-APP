import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { LearnChapterPage } from "../pages/student/LearnPage";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  getChapterContent: vi.fn(),
  getLearnProgress: vi.fn(),
  getSubjectChapters: vi.fn(),
  getSubjects: vi.fn(),
  upsertLearnProgress: vi.fn(),
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

function renderChapter() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <LearnChapterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("S1.3 unified workspace tabs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    window.history.pushState({}, "", "/student/learn/science/কোষ?class=6");
    apiMock.get.mockResolvedValue([]); // /learn/progress via get
    apiMock.getLearnProgress.mockResolvedValue([]);
    apiMock.upsertLearnProgress.mockResolvedValue({});
    apiMock.getChapterContent.mockResolvedValue({
      subject: "science",
      chapter: "কোষ",
      book: "বিজ্ঞান",
      class_level: 6,
      sections: [{ section: "কোষ কী", text: "জীবদেহের একক।" }],
    });
  });

  it("প্র্যাকটিস tab starts quiz with the chapter preselected", async () => {
    const user = userEvent.setup();
    apiMock.post.mockResolvedValue({
      attempt_id: 1,
      questions: [{ id: "q1", question_text: "কোষ কী?", options: ["a", "b"] }],
      requested: 5,
    });
    renderChapter();

    await user.click(await screen.findByRole("tab", { name: /অনুশীলন/ }));
    await user.click(await screen.findByRole("button", { name: /কুইজ শুরু/ }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        "/quizzes",
        expect.objectContaining({
          subject: "science",
          chapter: "কোষ",
          class_level: 6,
          student_id: 7,
        }),
      ),
    );
  });

  it("ask tab sends tutor request with chapter context", async () => {
    const user = userEvent.setup();
    apiMock.post.mockResolvedValue({
      answer: "কোষ হলো একক।",
      grounded: true,
      sources: [{ book: "বিজ্ঞান", chapter: "কোষ", score: 1 }],
    });
    renderChapter();

    await user.click(await screen.findByRole("tab", { name: /জিজ্ঞাসা/ }));
    await user.type(screen.getByRole("textbox"), "কোষ কী?");
    await user.click(screen.getByRole("button", { name: /পাঠান/ }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        "/tutor/ask",
        expect.objectContaining({
          subject: "science",
          chapter: "কোষ",
          class_level: 6,
        }),
      ),
    );
    expect(await screen.findByText("কোষ হলো একক।")).toBeTruthy();
  });

  it("read tab shows chapter content (default)", async () => {
    renderChapter();
    expect(await screen.findByText("কোষ কী")).toBeTruthy();
  });
});
