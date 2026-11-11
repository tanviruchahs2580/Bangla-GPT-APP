/**
 * FE-FIX-008: per-subject chapter counts were coerced to 0 on failure.
 *
 * A subject whose chapter list could not be read was handed a denominator of
 * zero, which silently removed its progress ring — the page answered "this
 * subject has no chapters" for a request that never came back, on the one
 * screen whose job is to say how far through the book a student is. The failed
 * subject is now omitted from the ring data (no fabricated denominator) and
 * the failure is named with a retry.
 *
 * The class chips and the ring are also the numeral-policy sites named for the
 * student's library: `LearnPage.tsx` printed the class levels and `done/total`
 * in Latin digits next to a Bangla aria-label.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LearnPage } from "../pages/student/LearnPage";
import { setLang, t } from "../i18n";
import type { SubjectOut } from "../types";

const apiMock = vi.hoisted(() => ({
  getSubjects: vi.fn(),
  getSubjectChapters: vi.fn(),
  getLearnProgress: vi.fn(),
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

const SUBJECTS: SubjectOut[] = [
  { subject: "science", book: "বিজ্ঞান", class_levels: [6] },
  { subject: "bangla", book: "বাংলা", class_levels: [6] },
];

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

const CHAPTER = {
  chapter: "কোষ",
  excerpt: "…",
  subject: "science",
  class_level: 6,
};

beforeEach(() => {
  vi.clearAllMocks();
  setLang("bn");
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
  apiMock.getSubjects.mockResolvedValue(SUBJECTS);
  apiMock.getLearnProgress.mockResolvedValue([
    { subject: "science", chapter: "কোষ", completed: true, read_pct: 100 },
  ]);
  apiMock.getSubjectChapters.mockImplementation((subject: string) =>
    subject === "science"
      ? Promise.resolve([CHAPTER])
      : Promise.reject(new Error("503")),
  );
});

describe("per-subject count failures", () => {
  it("names the failure and retries instead of hiding the ring", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText(t("progressLoadFailed"))).toBeTruthy();
    // The subject that answered keeps its measured ring...
    expect(
      screen.getByLabelText(t("chaptersDone", { done: 1, total: 1 })),
    ).toBeTruthy();
    // ...and the one that failed is not given an invented total: no ring at
    // all, rather than "০/০" under another subject's name.
    expect(
      screen.queryByLabelText(t("chaptersDone", { done: 0, total: 0 })),
    ).toBeNull();

    apiMock.getSubjectChapters.mockResolvedValue([CHAPTER]);
    await user.click(screen.getByRole("button", { name: t("retry") }));
    // Both subjects now have a real denominator: science 1/1, bangla 0/1.
    expect(
      await screen.findByLabelText(t("chaptersDone", { done: 0, total: 1 })),
    ).toBeTruthy();
    expect(screen.queryByText(t("progressLoadFailed"))).toBeNull();
  });

  it("renders the class levels and the ring in the language's digits", async () => {
    const { container } = renderPage();
    await screen.findByText(t("subjectScience"));

    const grid = container.querySelector(".subject-grid");
    expect(grid?.textContent).toContain("শ্রেণি ৬");
    expect(grid?.textContent).not.toContain("শ্রেণি 6");
    // done/total is a quantity pair, not a Latin fraction inside Bangla copy.
    expect(grid?.textContent).toContain("১/১");
  });
});
