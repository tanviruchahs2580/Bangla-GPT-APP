/** admin refusal audit card renders aggregate counts, never content. */

import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import AdminDashboard from "../pages/AdminDashboard";
import { formatNumber, t } from "../i18n";
import type { RefusalAudit } from "../types";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  // AdminDashboard now loads the feedback triage queue on mount.
  getFeedbackQueue: vi.fn(() =>
    Promise.resolve({
      rows: [],
      total: 0,
      open_count: 0,
      limit: 20,
      offset: 0,
    }),
  ),
  triageFeedback: vi.fn(),
  startImpersonation: vi.fn(),
}));

vi.mock("../api", () => ({
  ...apiMock,
  // AdminDashboard renders AiQualityCard, which calls the typed
  // client for this endpoint (it used to spell the path out here too).
  getAdminAiQuality: vi.fn(() => Promise.resolve(null)),
  apiBase: "/api",
  getToken: () => "tok",
}));

const AUDIT: RefusalAudit = {
  days: 30,
  total_refusals: 7,
  by_reason: { self_harm: 2, sexual_content: 5 },
  by_class: { "6": 4, "9": 3 },
  last_refusal_at: "2026-09-05T10:00:00",
};

beforeEach(() => {
  apiMock.get.mockReset().mockImplementation((url: string) => {
    if (url.startsWith("/admin/safety/refusals")) return Promise.resolve(AUDIT);
    if (url.startsWith("/admin/users")) {
      return Promise.resolve({ total: 0, items: [] });
    }
    if (url.startsWith("/admin/analytics/overview")) {
      return Promise.resolve({
        users_total: 0,
        students: 0,
        teachers: 0,
        admins: 1,
        parents: 0,
        quiz_attempts_graded: 0,
        avg_score_pct: null,
      });
    }
    return Promise.resolve([]);
  });
  apiMock.post.mockReset().mockResolvedValue({});
  apiMock.patch.mockReset().mockResolvedValue({});
  apiMock.del.mockReset().mockResolvedValue({});
});

// AdminDashboard now fetches through react-query (F-021), so every render
// needs a provider.
function renderAdmin() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminDashboard />
    </QueryClientProvider>,
  );
}

it("shows refusal totals, reasons and classes from the audit endpoint", async () => {
  renderAdmin();
  await waitFor(() => expect(screen.getByText(t("admSafety"))).toBeTruthy());
  await waitFor(() =>
    expect(screen.getByText(formatNumber(AUDIT.total_refusals))).toBeTruthy(),
  );
  // FE-FIX (raw machine copy): the aggregation keys are safety-screen
  // categories and tutor refuse-reason codes; they are mapped to copy, and the
  // raw snake_case identifiers must never reach the admin's screen.
  expect(screen.getByText(t("admRefReasonSelfHarm"))).toBeTruthy();
  expect(screen.getByText(t("admRefReasonSexualContent"))).toBeTruthy();
  expect(screen.queryByText("self_harm")).toBeNull();
  expect(screen.queryByText("sexual_content")).toBeNull();
  // Counts are quantities and take the language's digits.
  expect(
    screen.getByText(
      `${t("admRefusalClass")} ${formatNumber(6)}: ${formatNumber(4)}`,
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(
      `${t("admRefusalClass")} ${formatNumber(9)}: ${formatNumber(3)}`,
    ),
  ).toBeTruthy();
  expect(apiMock.get).toHaveBeenCalledWith("/admin/safety/refusals");
});

it("shows the empty state when nothing was refused", async () => {
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
    if (url.startsWith("/admin/users"))
      return Promise.resolve({ total: 0, items: [] });
    return Promise.resolve([]);
  });
  renderAdmin();
  await waitFor(() =>
    expect(screen.getByText(t("admNoRefusals"))).toBeTruthy(),
  );
  expect(screen.getByText(formatNumber(0))).toBeTruthy();
});

// FE-FIX-005: the query swallowed its own failure into `null`, which made the
// card's `refusals === null` branch permanent — on an outage the governance
// surface that shows what the safety screen refused sat on "লোড হচ্ছে…" for the
// rest of the session, indistinguishable from a slow load.
it("shows a retryable error instead of loading forever when the audit fails", async () => {
  apiMock.get.mockImplementation((url: string) => {
    if (url.startsWith("/admin/safety/refusals"))
      return Promise.reject(new Error("503"));
    if (url.startsWith("/admin/users"))
      return Promise.resolve({ total: 0, items: [] });
    return Promise.resolve([]);
  });
  renderAdmin();

  await waitFor(() =>
    expect(screen.getByText(t("errorGeneric"))).toBeTruthy(),
  );
  expect(screen.queryByText(t("loading"))).toBeNull();
  expect(
    screen.getAllByRole("button", { name: t("retry") }).length,
  ).toBeGreaterThan(0);
});
