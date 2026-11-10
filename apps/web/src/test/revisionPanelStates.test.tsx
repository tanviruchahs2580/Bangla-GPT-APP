/**
 * UX-003: the রিভিশন tab rendered nothing at all while its queue was loading
 * and nothing again after the request failed, so a slow or broken fetch was
 * indistinguishable from a broken app. The panel now has the same three
 * states its sibling AssignedPanel has: a status line while loading, a
 * retryable alert on failure, the empty copy only after a successful answer.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import QuizPage from "../pages/student/QuizPage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

const me = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "S",
  class_level: 6,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <QuizPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The revision tab, by the role the page's own tablist gives it. */
async function openRevision(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("tab", { name: new RegExp(t("revisionTab")) }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
  apiMock.post.mockResolvedValue({});
});

afterEach(() => cleanup());

describe("revision tab request states (UX-003)", () => {
  it("says it is loading instead of rendering an empty tab", async () => {
    const user = userEvent.setup();
    // A revision query that never settles: the student is waiting.
    apiMock.get.mockImplementation((path: string) =>
      path === "/revision/due" ? new Promise(() => {}) : Promise.resolve(null),
    );
    renderPage();
    await openRevision(user);

    expect(await screen.findByText(t("loading"))).toBeInTheDocument();
    expect(screen.queryByText(t("revisionEmpty"))).toBeNull();
  });

  it("surfaces a failed queue with a retry, not the empty copy", async () => {
    const user = userEvent.setup();
    apiMock.get.mockImplementation((path: string) =>
      path === "/revision/due"
        ? Promise.reject(new Error("boom"))
        : Promise.resolve(null),
    );
    renderPage();
    await openRevision(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      t("errorGeneric"),
    );
    // "nothing to revise today" after a failed request is a claim about the
    // student's work, not about the request.
    expect(screen.queryByText(t("revisionEmpty"))).toBeNull();

    const before = apiMock.get.mock.calls.filter(
      ([p]) => p === "/revision/due",
    ).length;
    await user.click(screen.getByRole("button", { name: t("retry") }));
    await waitFor(() =>
      expect(
        apiMock.get.mock.calls.filter(([p]) => p === "/revision/due").length,
      ).toBeGreaterThan(before),
    );
  });

  it("keeps the empty copy for a queue that really is empty", async () => {
    const user = userEvent.setup();
    apiMock.get.mockImplementation((path: string) =>
      path === "/revision/due"
        ? Promise.resolve({ today: "2026-01-05", due_count: 0, items: [] })
        : Promise.resolve(null),
    );
    renderPage();
    await openRevision(user);

    expect(await screen.findByText(t("revisionEmpty"))).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
