// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import AdminDashboard from "../pages/AdminDashboard";
import StatusPage from "../pages/StatusPage";
import { t } from "../i18n";
import type { FeedbackAdminRow, FeedbackQueuePage } from "../types";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  getFeedbackQueue: vi.fn(),
  triageFeedback: vi.fn(),
  startImpersonation: vi.fn(),
  getStatus: vi.fn(),
}));

vi.mock("../api", () => ({
  ...apiMock,
  // AdminDashboard renders AiQualityCard, which calls the typed
  // client for this endpoint (it used to spell the path out here too).
  getAdminAiQuality: vi.fn(() => Promise.resolve(null)),
  apiBase: "/api",
  getToken: () => "tok",
}));

const ROW: FeedbackAdminRow = {
  id: 9,
  user_id: 3,
  role: "student",
  rating: -1,
  comment: "answer was confusing",
  message_id: 4,
  attempt_id: null,
  triaged: false,
  triaged_at: null,
  note: null,
  created_at: "2026-09-05T10:00:00",
};

const QUEUE: FeedbackQueuePage = {
  rows: [ROW],
  total: 1,
  open_count: 1,
  limit: 20,
  offset: 0,
};

beforeEach(() => {
  vi.resetAllMocks();
  apiMock.get.mockImplementation((url: string) => {
    if (url.startsWith("/admin/safety/refusals")) {
      return Promise.resolve({
        days: 30,
        total_refusals: 0,
        by_reason: {},
        by_class: {},
        last_refusal_at: null,
      });
    }
    if (url.startsWith("/admin/schools")) return Promise.resolve([]);
    if (url.startsWith("/admin/content/versions")) return Promise.resolve([]);
    return Promise.resolve({
      total: 0,
      items: [],
      users_total: 0,
      students: 0,
      teachers: 0,
      parents: 0,
      quiz_attempts_graded: 0,
    });
  });
  apiMock.getFeedbackQueue.mockResolvedValue(QUEUE);
  apiMock.triageFeedback.mockResolvedValue({ ...ROW, triaged: true });
});

// AdminDashboard now fetches through react-query (F-021), so every render
// needs a provider.
function renderAdmin() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AdminDashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("feedback triage queue", () => {
  it("lists open feedback and marks an item triaged through the API", async () => {
    const user = userEvent.setup();
    renderAdmin();
    expect(await screen.findByText("answer was confusing")).toBeInTheDocument();
    expect(apiMock.getFeedbackQueue).toHaveBeenCalledWith("open");
    await user.click(screen.getByRole("button", { name: t("admMarkTriage") }));
    await waitFor(() => {
      expect(apiMock.triageFeedback).toHaveBeenCalledWith(9, { triaged: true });
    });
  });

  it("never shows reporter identity in the queue", async () => {
    renderAdmin();
    await screen.findByText("answer was confusing");
    expect(screen.queryByText("s@example.com")).toBeNull();
  });
});

describe("public status page", () => {
  it("renders components and an all-ok headline from the API", async () => {
    apiMock.getStatus.mockResolvedValue({
      status: "ok",
      components: [
        { name: "database", ok: true, detail: "queries responding" },
        { name: "cache", ok: true, detail: "shared cache reachable" },
        { name: "assistant", ok: true, detail: "provider configured" },
      ],
      checked_at: "2026-09-06T00:00:00",
    });
    render(
      <MemoryRouter>
        <StatusPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(t("statusAllOk"))).toBeInTheDocument();
    // FE-FIX-017: the API's English component names and details are mapped to
    // Bangla rather than printed verbatim — this page is linked from every
    // footer and was the only English left in the product. The server
    // contract is unchanged, so the test still drives it with the real
    // strings and asserts both halves: the Bangla is shown, the raw English
    // is not.
    expect(screen.getByText(t("statusCompDatabase"))).toBeInTheDocument();
    expect(screen.getByText(t("statusCompCache"))).toBeInTheDocument();
    expect(screen.getByText(t("statusDetailQueriesOk"))).toBeInTheDocument();
    expect(screen.getByText(t("statusDetailCacheShared"))).toBeInTheDocument();
    expect(screen.queryByText("queries responding")).not.toBeInTheDocument();
    expect(screen.queryByText("shared cache reachable")).not.toBeInTheDocument();
    expect(screen.queryByText("database")).not.toBeInTheDocument();
  });

  it("shows the degraded headline when any component fails", async () => {
    apiMock.getStatus.mockResolvedValue({
      status: "degraded",
      components: [{ name: "cache", ok: false, detail: "cache unreachable" }],
      checked_at: "2026-09-06T00:00:00",
    });
    render(
      <MemoryRouter>
        <StatusPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(t("statusDegraded"))).toBeInTheDocument();
    // FE-FIX-017: same contract as the all-ok case — the degraded detail is
    // mapped to Bangla, and the raw English the API sent is not rendered.
    expect(screen.getByText(t("statusCompCache"))).toBeInTheDocument();
    expect(screen.getByText(t("statusDetailCacheDown"))).toBeInTheDocument();
    expect(screen.queryByText("cache unreachable")).not.toBeInTheDocument();
  });
});
