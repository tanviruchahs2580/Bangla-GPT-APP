/** WP-DR: student home is capped at five primary blocks and the prompt
 *  bar hands the question straight to the AI tutor. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HomePage from "../pages/student/HomePage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
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
  name: "Rahim Uddin",
  class_level: 6,
};

const PROGRESS = {
  student: {},
  attempts_graded: 4,
  avg_score_pct: 72,
  by_chapter: [],
  weak_chapters: ["কোষ"],
};

const DASHBOARD = {
  user: me,
  today: "2026-09-13",
  continue_learning: {
    subject: "science",
    chapter: "কোষ",
    class_level: 6,
    excerpt: "কোষ হলো জীবদেহের একক",
  },
  quick_actions: [],
  recommendation: {
    type: "weak_chapter",
    subject: "science",
    chapter: "কোষ",
    reason: null,
  },
  progress: null,
};

const ACTIVITY = { days: [], streak: 3, minutes_total: 40 };

let tutorLocation: { pathname: string; state: unknown } | null = null;
function TutorProbe() {
  const loc = useLocation();
  tutorLocation = { pathname: loc.pathname, state: loc.state };
  return <div data-testid="tutor-probe">tutor</div>;
}

function renderHome() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/student"]}>
        <Routes>
          <Route path="/student" element={<HomePage />} />
          <Route path="/student/tutor" element={<TutorProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WP-DR student home", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem("lastChapter");
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    apiMock.get.mockImplementation((path: string) => {
      if (path.endsWith("/progress"))
        return Promise.resolve(structuredClone(PROGRESS));
      if (path === "/dashboard/summary")
        return Promise.resolve(structuredClone(DASHBOARD));
      if (path.endsWith("/activity"))
        return Promise.resolve(structuredClone(ACTIVITY));
      return Promise.resolve(null);
    });
  });

  it("shows at most five primary blocks with the required content", async () => {
    renderHome();

    // block 1: greeting + prompt bar
    expect(
      await screen.findByPlaceholderText(t("homePromptPlaceholder")),
    ).toBeInTheDocument();
    // block 2: continue learning (title + CTA both carry the label)
    expect(
      (await screen.findAllByText(new RegExp(t("continueLearning")))).length,
    ).toBeGreaterThan(0);
    // block 3: quick actions
    expect(
      screen.getByRole("group", { name: t("quickActionsLabel") }),
    ).toBeInTheDocument();
    // block 4: recommendation
    expect(
      await screen.findByText(new RegExp(t("todayRecommendation"))),
    ).toBeInTheDocument();
    // block 5: snapshot
    expect(screen.getByText(t("progressSnapshot"))).toBeInTheDocument();

    // the cap: exactly five <section>/<div> primary blocks in shell-main
    const main = document.querySelector("main.shell-main")!;
    const blocks = Array.from(main.children).filter(
      (el) => el.tagName === "SECTION" || el.classList.contains("card"),
    );
    expect(blocks.length).toBeLessThanOrEqual(5);
  });

  it("hands the typed question to the AI tutor", async () => {
    const user = userEvent.setup();
    renderHome();
    await user.type(
      screen.getByPlaceholderText(t("homePromptPlaceholder")),
      "ভগ্নাংশ বুঝাও",
    );
    await user.click(screen.getByRole("button", { name: t("homeAskBtn") }));
    expect(tutorLocation?.pathname).toBe("/student/tutor");
    expect((tutorLocation?.state as { ask?: string })?.ask).toBe(
      "ভগ্নাংশ বুঝাও",
    );
  });
});
