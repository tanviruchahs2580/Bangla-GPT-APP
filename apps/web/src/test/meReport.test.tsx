/**
 * The Me-page report sentence comes from the API as a code + params.
 *
 * Regression: the page called `t(code)` without the params, so a student whose
 * weak chapters triggered `sugg_practice_weak` saw the raw placeholder
 * "দুর্বল অধ্যায়গুলোতে বেশি অনুশীলন করুন: {chapters}।" in the UI.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MePage from "../pages/student/MePage";
import { t } from "../i18n";
import { suggestionSentence } from "../lib/text";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  generateInviteCode: vi.fn(),
  // The page calls this wrapper, not `get` directly (the real wrapper closes
  // over the real `get`, so mocking `get` alone would not intercept it).
  getMyReport: vi.fn(),
  apiBase: "/api",
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
}));
vi.mock("../AuthContext", () => authMock);

const me = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "S",
  class_level: 6,
};

function report(overrides: Record<string, unknown> = {}) {
  return {
    student_id: 1,
    name: "S",
    class_level: 6,
    period: "weekly",
    window_start: "2026-10-10T00:00:00",
    window_end: "2026-10-16T00:00:00",
    quizzes_taken: 3,
    quizzes_graded: 3,
    avg_score_pct: 62.0,
    chapters_read: 2,
    chapters_completed: 1,
    questions_asked: 5,
    weak_chapters: ["কোষ", "শ্বসন"],
    strengths: ["আলো"],
    suggestion_code: "sugg_practice_weak",
    suggestion_params: { chapters: ["কোষ", "শ্বসন"] },
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <MePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("me-page report suggestion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
  });

  it("renders the weak-chapter suggestion with the chapter names filled in", async () => {
    apiMock.getMyReport.mockResolvedValue(report());
    apiMock.get.mockResolvedValue(null);

    renderPage();

    // The sentence shares its <p> with the "পরামর্শ:" label, so match on the
    // document text rather than on a single element's exact text.
    const expected = t("sugg_practice_weak", { chapters: "কোষ, শ্বসন" });
    await waitFor(() => expect(document.body.textContent).toContain(expected));
    expect(document.body.textContent).not.toContain("{chapters}");
    expect(document.body.textContent).toContain("কোষ, শ্বসন");
  });

  // F-021: a failed report fetch used to unmount the whole report section —
  // including the weekly/monthly control — with no explanation.
  it("surfaces a failed report instead of dropping the section", async () => {
    apiMock.getMyReport.mockRejectedValue(new Error("boom"));
    apiMock.get.mockResolvedValue(null);

    renderPage();

    const title = await screen.findByText(t("myReportTitle"), undefined, {
      timeout: 8000,
    });
    const section = title.closest(".card") as HTMLElement;
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      t("errorGeneric"),
    );
    expect(
      within(section).getByRole("button", { name: t("retry") }),
    ).toBeInTheDocument();
  });

  it("has copy for every server-supplied note code", () => {
    // StudentMemoryOut.on_disable_note_code ships a code, not prose; a missing
    // dictionary entry renders the raw key to the student
    // ("memory_on_disable_note") exactly like the old {chapters} placeholder.
    expect(t("memory_on_disable_note")).not.toBe("memory_on_disable_note");
    expect(t("memory_on_disable_note").length).toBeGreaterThan(10);
  });

  it("fills the average-score suggestion too", () => {
    expect(
      suggestionSentence({
        suggestion_code: "sugg_keep_momentum",
        suggestion_params: { avg_score_pct: 88 },
      }),
    ).toBe(t("sugg_keep_momentum", { avg_score_pct: "88" }));
  });

  it("falls back to the raw code when the server sends an unknown one", () => {
    expect(
      suggestionSentence({
        suggestion_code: "sugg_from_the_future",
        suggestion_params: {},
      }),
    ).toBe("sugg_from_the_future");
  });

  it("does not print a placeholder when params are missing", () => {
    expect(
      suggestionSentence({ suggestion_code: "sugg_general_support" }),
    ).toBe(t("sugg_general_support"));
  });
});
