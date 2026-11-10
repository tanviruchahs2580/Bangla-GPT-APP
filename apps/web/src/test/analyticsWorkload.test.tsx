/**
 * UX-004: a failed or in-flight workload fetch was reported as "এখন পর্যন্ত
 * কোনো ডকুমেন্ট নেই". `workloadQuery.data ?? null` collapsed three different
 * situations — loading, failed, genuinely empty — into the empty copy, so an
 * outage became a claim about the teacher's own work. The card branches on
 * the request state first, like the AI-insight and weak-matrix cards on the
 * same page.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AnalyticsPage from "../pages/teacher/AnalyticsPage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  getTeacherWorkload: vi.fn(),
}));

vi.mock("../api", () => ({
  ...apiMock,
  apiBase: "/api",
  getToken: () => "tok",
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../AuthContext", () => authMock);

const me = {
  user_id: 2,
  email: "t@x.com",
  role: "teacher",
  profile_id: null,
  name: "Karima Begum",
  class_level: null,
};

const ROOMS = [{ id: 1, class_level: 6, section: "GEN", student_count: 2 }];

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/teacher/analytics"]}>
        <Routes>
          <Route path="/teacher/analytics" element={<AnalyticsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The capacity card, which owns the workload figure and its empty copy. */
function capacityCard(): HTMLElement {
  return screen
    .getByText(t("anaCapacity"))
    .closest("section.card") as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/teacher/classrooms")
      return Promise.resolve(structuredClone(ROOMS));
    if (path === "/teacher/curriculum-coverage")
      return Promise.resolve({ subjects: [], cells: [] });
    if (path === "/teacher/support-plans") return Promise.resolve([]);
    if (path.includes("weak-matrix")) return Promise.resolve(null);
    return Promise.resolve(null);
  });
});

afterEach(() => cleanup());

describe("capacity card request states", () => {
  it("reports a failed workload fetch as a failed request, not an empty library", async () => {
    apiMock.getTeacherWorkload.mockRejectedValue(new Error("boom"));
    renderPage();

    const card = await waitFor(() => capacityCard());
    expect(await within(card).findByRole("alert")).toHaveTextContent(
      t("errorGeneric"),
    );
    expect(within(card).queryByText(t("noDocumentsYet"))).toBeNull();
    expect(
      within(card).getByRole("button", { name: t("retry") }),
    ).toBeInTheDocument();
  });

  it("keeps the workload figure for a fetch that answered", async () => {
    apiMock.getTeacherWorkload.mockResolvedValue({
      counts: {},
      minutes_saved: {},
      total_minutes_saved: 42,
      estimate: true,
      methodology: "heuristic",
    });
    renderPage();

    const card = await waitFor(() => capacityCard());
    expect(
      await within(card).findByText(t("workloadMinutes", { n: 42 })),
    ).toBeInTheDocument();
    expect(within(card).queryByText(t("noDocumentsYet"))).toBeNull();
    expect(within(card).queryByRole("alert")).toBeNull();
  });

  it("retries from the failed card", async () => {
    const user = userEvent.setup();
    apiMock.getTeacherWorkload.mockRejectedValueOnce(new Error("boom"));
    renderPage();

    const card = await waitFor(() => capacityCard());
    await within(card).findByRole("alert");
    apiMock.getTeacherWorkload.mockResolvedValue({
      counts: {},
      minutes_saved: {},
      total_minutes_saved: 7,
      estimate: true,
      methodology: "heuristic",
    });
    await user.click(within(card).getByRole("button", { name: t("retry") }));

    expect(
      await within(card).findByText(t("workloadMinutes", { n: 7 })),
    ).toBeInTheDocument();
  });
});
