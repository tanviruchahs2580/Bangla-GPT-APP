import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { LearnChapterPage } from "../pages/student/LearnPage";
import { clearOfflineChapters } from "../lib/offlineStore";
import { t } from "../i18n";

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

describe("unified workspace tabs", () => {
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

  it("practice options keep the quiz page's keyboard contract", async () => {
    // The tab used to render its own radiogroup: role="radio" on every option
    // with all of them in the tab order and no arrow keys — the defect
    // QuizPage was fixed for, still present here because the widget had been
    // duplicated instead of shared.
    const user = userEvent.setup();
    apiMock.post.mockResolvedValue({
      attempt_id: 2,
      questions: [
        { id: "q1", question_text: "কোষ কী?", options: ["a", "b", "c"] },
      ],
      requested: 5,
    });
    renderChapter();

    await user.click(await screen.findByRole("tab", { name: /অনুশীলন/ }));
    await user.click(await screen.findByRole("button", { name: /কুইজ শুরু/ }));

    const group = await screen.findByRole("radiogroup", { name: "কোষ কী?" });
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(3);
    // one tab stop for the group, and it is the first option before a choice
    expect(
      radios.filter((r) => r.getAttribute("tabindex") === "0"),
    ).toHaveLength(1);
    expect(radios[0].getAttribute("tabindex")).toBe("0");

    radios[0].focus();
    await user.keyboard("{ArrowDown}");
    expect(radios[1]).toHaveAttribute("aria-checked", "true");
    expect(document.activeElement).toBe(radios[1]);
    await user.keyboard("{ArrowUp}");
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
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

  it("read tab reports a failed fetch as an error, not as an empty subject", async () => {
    apiMock.getChapterContent
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({
        subject: "science",
        chapter: "কোষ",
        book: "বিজ্ঞান",
        class_level: 6,
        sections: [{ section: "কোষ কী", text: "জীবদেহের একক।" }],
      });

    renderChapter();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(t("loadFailed"));
    // "No chapters found for this subject" would be a lie about the corpus.
    expect(screen.queryByText(t("noChapters"))).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: t("retry") }));
    expect(await screen.findByText("কোষ কী")).toBeTruthy();
  });

  it("the offline copy control exposes its saved state (F-203)", async () => {
    // The button used to change only its pixels: the accessible name stayed
    // "Download chapter" and nothing said the chapter was saved, so a screen
    // reader could not tell the copy was on the device.
    await clearOfflineChapters();
    renderChapter();
    const button = await screen.findByRole("button", {
      name: t("downloadChapter"),
    });
    expect(button).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(button);
    await waitFor(() =>
      expect(button).toHaveAttribute("aria-pressed", "true"),
    );
    // The visible label switches to "Saved" as well; both channels agree.
    expect(button).toHaveTextContent(t("downloaded"));
    await clearOfflineChapters();
  });
});
