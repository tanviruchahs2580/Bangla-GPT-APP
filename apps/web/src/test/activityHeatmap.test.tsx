import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import MePage from "../pages/student/MePage";
import { t } from "../i18n";
import type { ActivityDay, ActivitySummary } from "../types";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  generateInviteCode: vi.fn(),
  apiBase: "/api",
}));

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

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

function summary(): ActivitySummary {
  const days: ActivityDay[] = Array.from({ length: 91 }, (_, i) => {
    const d = new Date(Date.UTC(2026, 5, 1 + i));
    const iso = d.toISOString().slice(0, 10);
    if (i === 90) return { date: iso, questions: 6, quizzes: 1, minutes: 7 };
    if (i === 89) return { date: iso, questions: 2, quizzes: 0, minutes: 2 };
    if (i === 88) return { date: iso, questions: 1, quizzes: 0, minutes: 1 };
    return { date: iso, questions: 0, quizzes: 0, minutes: 0 };
  });
  return { streak: 3, today: days[90].date, days };
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

describe("S1.9 streak heatmap UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    apiMock.get.mockImplementation((path: string) => {
      if (path.startsWith("/students/7/activity"))
        return Promise.resolve(summary());
      return Promise.resolve(null);
    });
  });

  it("renders one heat cell per day, the streak label and activity levels", async () => {
    const { container } = renderPage();

    expect(
      await screen.findByText(t("streakLabel", { days: 3 })),
    ).toBeInTheDocument();

    const cells = container.querySelectorAll(".heat-cell");
    expect(cells.length).toBe(91);
    // Level math: 6+1 => lvl-3, 2 => lvl-1, 1 => lvl-1, zeros => lvl-0.
    expect(container.querySelectorAll(".heat-cell.lvl-3").length).toBe(1);
    expect(container.querySelectorAll(".heat-cell.lvl-1").length).toBe(2);
    expect(container.querySelectorAll(".heat-cell.lvl-0").length).toBe(88);

    const hot = container.querySelector(".heat-cell.lvl-3") as HTMLElement;
    expect(hot.getAttribute("title")).toContain(
      t("activityQuestions", { n: 6 }),
    );
    expect(hot.getAttribute("title")).toContain(t("activityMinutes", { n: 7 }));
  });

  it("asks the API for the signed-in student profile", async () => {
    renderPage();
    await screen.findByText(t("streakLabel", { days: 3 }));
    expect(apiMock.get).toHaveBeenCalledWith("/students/7/activity");
  });
});
