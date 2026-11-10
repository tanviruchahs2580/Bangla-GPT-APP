/**
 * FE-FIX-011: the optimistic bookmark never rolled back.
 *
 * `setBookmarked(next)` ran before the write, the failure was swallowed, and
 * the button kept the new state — so the UI asserted a stored bookmark that did
 * not exist. A bookmark is how a student keeps a chapter; claiming it is saved
 * when the write failed is the whole failure. The optimistic flip now reverts
 * and says so, without dropping the reader out of the chapter.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LearnChapterPage } from "../pages/student/LearnPage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  getChapterContent: vi.fn(),
  getLearnProgress: vi.fn(),
  getSubjectChapters: vi.fn(),
  getSubjects: vi.fn(),
  post: vi.fn(),
  upsertLearnProgress: vi.fn(),
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

function renderReader() {
  window.history.pushState(
    {},
    "",
    `/student/learn/science/${encodeURIComponent("কোষ")}?class=6`,
  );
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

beforeEach(() => {
  vi.clearAllMocks();
  document.querySelectorAll(".toast-region").forEach((el) => el.remove());
  authMock.useAuth.mockReturnValue({
    me: {
      user_id: 1,
      email: "s@x.com",
      role: "student",
      profile_id: 7,
      name: "S",
      class_level: 6,
    },
    signOut: vi.fn(),
  });
  apiMock.getChapterContent.mockResolvedValue({
    subject: "science",
    chapter: "কোষ",
    class_level: 6,
    book: "বিজ্ঞান",
    sections: [{ section: "১", text: "টেক্সট" }],
  });
  // `bookmarked` is part of the payload the page syncs its button from: a
  // fixture without it wipes the state on the next refetch.
  apiMock.getLearnProgress.mockResolvedValue([
    {
      subject: "science",
      chapter: "কোষ",
      completed: false,
      read_pct: 40,
      bookmarked: false,
    },
  ]);
  apiMock.getSubjectChapters.mockResolvedValue([]);
  apiMock.getSubjects.mockResolvedValue([]);
  apiMock.upsertLearnProgress.mockResolvedValue({});
});

describe("bookmark write failures", () => {
  it("rolls the optimistic bookmark back and tells the student", async () => {
    const user = userEvent.setup();
    apiMock.upsertLearnProgress.mockRejectedValue(new Error("500"));
    renderReader();

    const bookmark = await screen.findByRole("button", {
      name: t("bookmark"),
    });
    expect(bookmark).toHaveAttribute("aria-pressed", "false");

    await user.click(bookmark);

    // The record is dishonest for at most the duration of the request; it must
    // not survive the failure.
    expect(await screen.findByText(t("errorGeneric"))).toBeTruthy();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: t("bookmark") }),
      ).toHaveAttribute("aria-pressed", "false"),
    );
  });

  it("keeps the bookmark when the write lands", async () => {
    const user = userEvent.setup();
    renderReader();
    const bookmark = await screen.findByRole("button", {
      name: t("bookmark"),
    });
    await user.click(bookmark);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: t("bookmark") }),
      ).toHaveAttribute("aria-pressed", "true"),
    );
    expect(screen.queryByText(t("errorGeneric"))).toBeNull();
  });
});

// FE-FIX (raw machine copy + numerals): the reader header printed the API enum
// ("science") and the class level in Latin digits, in an otherwise Bangla
// header whose neighbouring badges are localized.
describe("reader header copy", () => {
  it("localizes the subject and the class level", async () => {
    renderReader();
    await screen.findByRole("button", { name: t("bookmark") });

    // The subject badge is the localized label, and the enum never appears:
    // "বিজ্ঞান" is also the book title, so match the header badge itself.
    const badge = screen
      .getAllByText(t("subjectScience"))
      .find((el) => el.classList.contains("badge"));
    expect(badge).toBeTruthy();
    expect(screen.queryByText("science")).toBeNull();
    expect(screen.getByText(/^শ্রেণি\s*৬$/)).toBeTruthy();
  });
});
