import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import MePage from "../pages/student/MePage";
import { friendlyError } from "../errors";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  generateInviteCode: vi.fn(),
  // The page reads its sections through these wrappers. They are mocked with
  // benign payloads so a test that fails ONE call (the export) still exercises
  // the other sections' happy path: since F-021 every failed section renders a
  // retryable LoadError, and a blanket `null` mock would make the page look
  // like four simultaneous outages rather than the single export failure the
  // test is about.
  getMyPrefs: vi.fn(),
  getMyMemory: vi.fn(),
  getNotes: vi.fn(),
  getMyReport: vi.fn(),
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

const EXPORT_PAYLOAD = {
  user: { id: 1, email: "s@x.com", role: "student" },
  profile: { type: "student", id: 7 },
  quiz_attempts: [],
  parent_links: [],
};

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

describe("data export button (BUG-2 regression)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    apiMock.getMyPrefs.mockResolvedValue({
      memory_enabled: true,
      learning_prefs: { explanation_style: "standard", subject_focus: "" },
    });
    apiMock.getMyMemory.mockResolvedValue({ memory_enabled: true, facts: [] });
    apiMock.getNotes.mockResolvedValue([]);
    apiMock.getMyReport.mockResolvedValue(null);
    apiMock.get.mockImplementation((path: string) => {
      if (path === "/users/me/export") return Promise.resolve(EXPORT_PAYLOAD);
      if (path.endsWith("/activity")) {
        return Promise.resolve({ days: [], streak: 0, minutes: 0 });
      }
      return Promise.resolve(null);
    });
    // jsdom does not implement blob URLs; stub the object-URL round-trip.
    URL.createObjectURL = vi.fn(() => "blob:mock-export");
    URL.revokeObjectURL = vi.fn();
  });

  it("fetches the export with the authed API client instead of a plain anchor link", async () => {
    const { container } = renderPage();
    // The old implementation was a bare <a href="/api/users/me/export">, which
    // the browser fetched without the bearer token and got a 401.
    expect(
      container.querySelector('a[href="/api/users/me/export"]'),
    ).toBeNull();

    await userEvent.click(await screen.findByText(t("exportData")));

    expect(apiMock.get).toHaveBeenCalledWith("/users/me/export");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    // The object URL is released on a later task, not on the line after
    // click(): revoking immediately can cancel a download the browser
    // resolved asynchronously (lib/download.ts documents the race).
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  });

  it("surfaces a friendly error when the export call fails", async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path === "/users/me/export") return Promise.reject(new Error("nope"));
      if (path.endsWith("/activity")) {
        return Promise.resolve({ days: [], streak: 0, minutes: 0 });
      }
      return Promise.resolve(null);
    });
    renderPage();
    const exportButton = await screen.findByText(t("exportData"));
    await userEvent.click(exportButton);
    // Scoped to the export card: the same generic copy can legitimately appear
    // in other sections' LoadError blocks, and the assertion here is about the
    // export path specifically.
    const exportCard = exportButton.closest(".card") as HTMLElement;
    expect(exportCard).not.toBeNull();
    await waitFor(() =>
      expect(
        within(exportCard).getByText(friendlyError("nope").text),
      ).toBeInTheDocument(),
    );
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
