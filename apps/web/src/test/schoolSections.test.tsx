/**
 * F-022: SchoolSections had five useQuery calls whose isPending/isError were
 * never read, so a failing /school/* request rendered an empty dashboard —
 * no spinner, no error, no way to retry. Each section now owns its states.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SchoolSections } from "../components/school/SchoolSections";
import { t } from "../i18n";
import type { SchoolStudentPage } from "../api";

const apiMock = vi.hoisted(() => ({
  getSchoolStudents: vi.fn(),
  getSchoolTeachers: vi.fn(),
  getSchoolClasses: vi.fn(),
  getSchoolCoverage: vi.fn(),
  getSchoolAnalytics: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
}));

const STUDENTS: SchoolStudentPage = {
  total: 1,
  limit: 100,
  offset: 0,
  items: [
    {
      student_id: 11,
      name: "Rahim",
      class_level: 6,
      section: "GEN",
      last_active: null,
      quiz_attempts: 3,
    },
  ],
};

function resolveAll() {
  apiMock.getSchoolStudents.mockResolvedValue(structuredClone(STUDENTS));
  apiMock.getSchoolTeachers.mockResolvedValue([]);
  apiMock.getSchoolClasses.mockResolvedValue([]);
  apiMock.getSchoolCoverage.mockResolvedValue({ rows: [] });
  apiMock.getSchoolAnalytics.mockResolvedValue({
    days: 30,
    active_by_date: [],
    daily_active_avg: 0,
    questions_asked: 0,
    quiz_attempts: 0,
    attempts_graded: 0,
    avg_quiz_score_pct: null,
  });
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SchoolSections />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  resolveAll();
});

describe("school dashboard sections (F-022)", () => {
  it("renders a retryable error per section instead of an empty dashboard", async () => {
    for (const fn of Object.values(apiMock)) {
      fn.mockRejectedValue(new Error("down"));
    }
    renderPage();

    // Every one of the five sections reports the failure — previously all
    // five silently rendered nothing.
    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(5);
    expect(alerts[0]).toHaveTextContent(t("errorGeneric"));
    expect(screen.getAllByRole("button", { name: t("retry") })).toHaveLength(5);
    // The section headings are present (the admin can see what failed).
    expect(
      screen.getByRole("region", { name: t("students") }),
    ).toBeInTheDocument();
  });

  it("shows a loading state while a section request is in flight", async () => {
    apiMock.getSchoolStudents.mockReturnValue(new Promise(() => {}));
    renderPage();

    const card = await screen.findByRole("region", { name: t("students") });
    expect(within(card).getByRole("status")).toHaveTextContent(t("loading"));
    // The sections that already resolved render normally alongside it.
    expect(await screen.findByText(t("covEmpty"))).toBeInTheDocument();
  });

  it("recovers through the retry button without a reload", async () => {
    const user = userEvent.setup();
    apiMock.getSchoolStudents
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValue(structuredClone(STUDENTS));
    renderPage();

    // Wait for the failure state (the card starts as "loading").
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const card = screen.getByRole("region", { name: t("students") });
    await user.click(within(card).getByRole("button", { name: t("retry") }));

    expect(await screen.findByText("Rahim")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
