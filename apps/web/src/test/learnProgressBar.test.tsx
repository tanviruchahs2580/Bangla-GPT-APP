/**
 * The chapter list used to render `pct = prog ? 45 : 0`: every in-progress
 * chapter claimed the same invented 45%, so a chapter read to 20% and one read
 * to 90% looked identical, and the bar's aria-label announced "45%" as if a
 * measurement had been taken. The value the reader actually writes is
 * `read_pct`, which is also what the status badge uses.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { LearnPage } from "../pages/student/LearnPage";
import { tSubject } from "../i18n";

const apiMock = vi.hoisted(() => ({
  getSubjects: vi.fn(),
  getSubjectChapters: vi.fn(),
  getLearnProgress: vi.fn(),
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <LearnPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openChapters(progress: unknown[] = []) {
  apiMock.getSubjects.mockResolvedValue([
    { subject: "science", book: "বিজ্ঞান", class_levels: [6] },
  ]);
  apiMock.getSubjectChapters.mockResolvedValue([
    { chapter: "কোষ", excerpt: "…" },
  ]);
  // The progress rows must be in place BEFORE the first render: react-query
  // caches the response for the key, so a late mock never refetches.
  apiMock.getLearnProgress.mockResolvedValue(progress);
  renderPage();
  const card = await screen.findByRole("button", {
    name: new RegExp(tSubject("science")),
  });
  await userEvent.click(card);
  await screen.findByText(/কোষ/);
}

describe("chapter progress bar reports the recorded progress", () => {
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
  });

  it("draws the reader's own percentage, not a placeholder", async () => {
    await openChapters([
      { subject: "science", chapter: "কোষ", read_pct: 20, completed: false },
    ]);

    // Generous timeout on purpose: the bar renders once the progress query
    // settles, and the full suite runs 69 files in parallel. A tight budget
    // here would make this gate flaky, which is worse than no gate.
    const bar = await screen.findByRole(
      "img",
      { name: "20%" },
      { timeout: 8000 },
    );
    expect(bar.querySelector("span")).toHaveStyle({ width: "20%" });
    expect(screen.queryByRole("img", { name: "45%" })).toBeNull();
  });

  it("renders no bar for a chapter that was never opened", async () => {
    await openChapters();
    await waitFor(() =>
      expect(screen.queryByRole("img", { name: /%/ })).toBeNull(),
    );
  });
});
