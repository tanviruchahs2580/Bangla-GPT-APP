/**
 * FE-FIX-007: the teacher home ignored `draftsQuery`.
 *
 * The drafts stat degraded to an unexplained "—" when its request failed (the
 * teacher could not tell an empty backlog from a broken read) and the banner's
 * retry refetched the other two queries only, so the number stayed wrong until
 * a reload.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TeacherHomePage from "../pages/teacher/TeacherHomePage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  getTeacherWorkload: vi.fn(),
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
        <TeacherHomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({
    me: { user_id: 3, email: "t@x.com", role: "teacher", name: "T" },
    signOut: vi.fn(),
  });
  apiMock.get.mockResolvedValue([]);
  apiMock.getTeacherWorkload.mockResolvedValue({
    total_minutes_saved: 30,
    methodology: "estimate",
  });
});

describe("teacher home draft-count failures", () => {
  it("includes the drafts query in the banner and re-runs it on retry", async () => {
    const user = userEvent.setup();
    apiMock.get.mockImplementation((url: string) => {
      if (url.includes("/teacher/qpapers"))
        return Promise.reject(new Error("500"));
      return Promise.resolve([]);
    });
    renderPage();

    // The banner covers the drafts query now — "—" is no longer unexplained.
    expect(await screen.findByText(new RegExp(t("thLoadError")))).toBeTruthy();
    const before = apiMock.get.mock.calls.length;

    apiMock.get.mockResolvedValue([]);
    await user.click(screen.getByRole("button", { name: t("retry") }));

    await waitFor(() =>
      expect(apiMock.get.mock.calls.length).toBeGreaterThan(before),
    );
    // The retry really re-asked the drafts endpoint.
    expect(
      apiMock.get.mock.calls.some(([url]) =>
        String(url).includes("/teacher/qpapers"),
      ),
    ).toBe(true);
    await waitFor(() =>
      expect(screen.queryByText(new RegExp(t("thLoadError")))).toBeNull(),
    );
  });
});
