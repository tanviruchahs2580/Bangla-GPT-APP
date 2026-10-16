/**
 * F-021 / F-023: AdminDashboard listed the live search string in its effect
 * dependencies, so every keystroke fired five authenticated requests with no
 * debounce and no cancellation. The page now fetches through the shared
 * react-query client, with a debounced query key for the email search.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminDashboard from "../pages/AdminDashboard";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  getFeedbackQueue: vi.fn(),
  triageFeedback: vi.fn(),
  startImpersonation: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
}));

const EMPTY_QUEUE = {
  rows: [],
  total: 0,
  open_count: 0,
  limit: 20,
  offset: 0,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminDashboard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/users"))
      return Promise.resolve({ total: 0, items: [] });
    if (path === "/admin/analytics/overview") {
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
    if (path === "/admin/schools/stats") return Promise.resolve([]);
    if (path === "/admin/content/versions") return Promise.resolve([]);
    if (path === "/admin/safety/refusals")
      return Promise.resolve({
        days: 30,
        total_refusals: 0,
        by_reason: {},
        by_class: {},
        last_refusal_at: null,
      });
    return Promise.resolve(null);
  });
  apiMock.getFeedbackQueue.mockResolvedValue(EMPTY_QUEUE);
});

/** All /admin/users calls that carried a search string. */
function searchCalls(): string[] {
  return apiMock.get.mock.calls
    .map(([path]) => String(path))
    .filter((path) => path.startsWith("/admin/users") && path.includes("q="));
}

describe("admin user search debounce (F-023)", () => {
  it("fires one users request for a typed burst, after the debounce", async () => {
    renderPage();
    await screen.findByText(t("admSchools"));

    const input = screen.getByLabelText(t("searchEmail"));
    // A burst of keystrokes: pre-fix this fired one query per character.
    fireEvent.change(input, { target: { value: "a" } });
    fireEvent.change(input, { target: { value: "ab" } });
    fireEvent.change(input, { target: { value: "abc" } });

    await waitFor(() => expect(searchCalls()).toHaveLength(1), {
      timeout: 3000,
    });
    expect(searchCalls()[0]).toContain("q=abc");

    // Nothing fires later for the superseded strings.
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(searchCalls()).toHaveLength(1);
  });

  it("sends the search term and the role filter in one query key", async () => {
    renderPage();
    await screen.findByText(t("admSchools"));

    fireEvent.change(screen.getByLabelText(t("searchEmail")), {
      target: { value: "teacher@school.edu.bd" },
    });
    fireEvent.change(screen.getByLabelText(t("role")), {
      target: { value: "teacher" },
    });

    await waitFor(() =>
      expect(
        searchCalls().some(
          (path) =>
            path.includes("q=teacher%40school.edu.bd") &&
            path.includes("role=teacher"),
        ),
      ).toBe(true),
    );
    // The role change is not debounced (only the text input is).
    expect(searchCalls()).toHaveLength(1);
  });
});
