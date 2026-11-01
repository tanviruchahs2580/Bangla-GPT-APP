import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { t } from "../i18n";
import { LearnChapterPage } from "../pages/student/LearnPage";

// F-110: starting a chapter quiz that fails with index_unavailable used to
// print the API's raw English detail.message ("Curriculum index unavailable")
// into the Bangla screen. It must show the localized retryable copy instead.
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

describe("chapter practice start failure copy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
      class_level: 6,
      book: "বিজ্ঞান",
      chapter: "কোষ",
      sections: [{ section: "কোষ", text: "কোষ হলো জীবের গঠনমূলক একক।" }],
    });
    apiMock.getLearnProgress.mockResolvedValue([]);
    apiMock.upsertLearnProgress.mockResolvedValue({});
  });

  it("shows the localized retry copy, never the raw API message", async () => {
    const user = userEvent.setup();
    apiMock.post.mockRejectedValue(
      Object.assign(new Error("422"), {
        rawDetail: {
          detail: {
            code: "index_unavailable",
            message: "Curriculum index unavailable",
          },
        },
      }),
    );
    renderReader();

    await user.click(
      await screen.findByRole("tab", { name: t("tabPractice") }),
    );
    await user.click(
      await screen.findByRole("button", { name: t("startQuiz") }),
    );

    expect(await screen.findByText(t("errLlmUnavailable"))).toBeInTheDocument();
    expect(screen.queryByText(/Curriculum index/)).not.toBeInTheDocument();
  });
});
