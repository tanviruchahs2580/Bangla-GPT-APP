/** admin center renders school stats, version rows, invite create/revoke. */

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminDashboard from "../pages/AdminDashboard";
import { t } from "../i18n";
import type {
  AdminSchoolStats,
  ContentVersionRow,
  SchoolInviteAdmin,
} from "../types";

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

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
  apiBase: "/api",
  getToken: () => "tok",
}));

const SCHOOLS: AdminSchoolStats[] = [
  {
    id: 1,
    name: "Adm School",
    code: "SCH-ABC",
    created_at: "2026-09-01T00:00:00",
    teachers: 1,
    classrooms: 2,
    students: 2,
    sessions_7d: 4,
  },
];

const VERSIONS: ContentVersionRow[] = [
  {
    subject: "science",
    class_level: 6,
    chapter: "chA",
    current_version: 3,
    versions_total: 3,
    source: "teacher",
    updated_at: "2026-09-01T00:00:00",
    updated_by_email: "root@example.com",
  },
];

const INVITES: SchoolInviteAdmin[] = [
  {
    id: 5,
    school_id: 1,
    role: "teacher",
    used: false,
    created_at: "2026-09-01T10:00:00",
    used_at: null,
  },
  {
    id: 4,
    school_id: 1,
    role: "school_admin",
    used: true,
    created_at: "2026-08-30T10:00:00",
    used_at: "2026-08-31T10:00:00",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/users")) {
      return Promise.resolve({ total: 0, items: [] });
    }
    if (path === "/admin/analytics/overview") {
      return Promise.resolve({
        users_total: 5,
        students: 3,
        teachers: 1,
        admins: 1,
        parents: 0,
        quiz_attempts_graded: 7,
        avg_score_pct: 65,
      });
    }
    if (path === "/admin/schools/stats")
      return Promise.resolve(structuredClone(SCHOOLS));
    if (path === "/admin/content/versions")
      return Promise.resolve(structuredClone(VERSIONS));
    if (path === "/admin/schools/1/invites")
      return Promise.resolve(structuredClone(INVITES));
    return Promise.resolve(null);
  });
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

describe("admin center", () => {
  it("renders per-school stats and current content versions", async () => {
    renderAdmin();
    await screen.findByText(t("admSchools"));
    // findBy*, not getBy*: the schools and versions cards own their queries
    // since the F-094 split, so each fetched value arrives on its own tick
    // and a synchronous sample of the first commit is a race (the whole
    // assertions are unchanged otherwise).
    expect(await screen.findByText("Adm School")).toBeInTheDocument();
    expect(await screen.findByText("SCH-ABC")).toBeInTheDocument();
    expect(await screen.findByText("4")).toBeInTheDocument(); // sessions_7d
    expect(await screen.findByText("science · 6")).toBeInTheDocument();
    expect(await screen.findByText("v3 (3)")).toBeInTheDocument();
    expect(await screen.findByText("root@example.com")).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith("/admin/schools/stats");
    expect(apiMock.get).toHaveBeenCalledWith("/admin/content/versions");
  });

  it("shows empty hints when there is nothing yet", async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path === "/admin/schools/stats") return Promise.resolve([]);
      if (path === "/admin/content/versions") return Promise.resolve([]);
      if (path.startsWith("/admin/users"))
        return Promise.resolve({ total: 0, items: [] });
      return Promise.resolve(null);
    });
    renderAdmin();
    await waitFor(() =>
      expect(screen.getByText(t("admNoSchools"))).toBeInTheDocument(),
    );
    expect(await screen.findByText(t("admNoVersions"))).toBeInTheDocument();
  });

  it("creates an invite once (plaintext shown once) and revokes an active one", async () => {
    apiMock.post.mockResolvedValue({ code: "INVITECODEX1" });
    apiMock.del.mockResolvedValue(undefined);
    renderAdmin();
    await screen.findByText("Adm School");

    fireEvent.click(screen.getByRole("button", { name: t("admInvite") }));
    await screen.findByText("INVITECODEX1");
    expect(apiMock.post).toHaveBeenCalledWith("/schools/1/invites", {
      role: "teacher",
    });

    // open the invite list for school 1
    fireEvent.click(
      screen.getByRole("button", { name: `Adm School ${t("admInvites")}` }),
    );
    await screen.findByText(t("admInvites"));
    expect(screen.getByText(t("admActive"))).toBeInTheDocument();
    expect(screen.getByText(t("admUsed"))).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: t("admRevoke") }));
    await waitFor(() =>
      expect(apiMock.del).toHaveBeenCalledWith("/admin/schools/1/invites/5"),
    );
    await waitFor(() =>
      expect(screen.getByText(t("admRevoked"))).toBeInTheDocument(),
    );
  });

  it("offers school_admin as a role and shows a school_admin row as itself", async () => {
    const original = apiMock.get.getMockImplementation() as
      ((path: string) => Promise<unknown>) | undefined;
    apiMock.get.mockImplementation((path: string) => {
      if (path.startsWith("/admin/users")) {
        return Promise.resolve({
          total: 1,
          items: [
            {
              id: 7,
              email: "head@school.edu.bd",
              role: "school_admin",
              created_at: "2026-09-01T00:00:00",
            },
          ],
        });
      }
      return original!(path);
    });

    renderAdmin();
    const select = await screen.findByRole("combobox", {
      name: /head@school\.edu\.bd/,
    });

    // Before the fix school_admin was absent from the option list, so the row
    // rendered the first option ("student") and any edit would have demoted them.
    expect((select as HTMLSelectElement).value).toBe("school_admin");
    // Found by its machine value, not by its text: the label is localized now,
    // and the guarantee this test exists for is that the option is present with
    // the value the API expects.
    const option = within(select)
      .getAllByRole("option")
      .find(
        (o) => (o as HTMLOptionElement).value === "school_admin",
      ) as HTMLOptionElement;
    expect(option).toBeDefined();
    expect(option.textContent).toBe(t("roleSchoolAdmin"));
    expect(option.textContent).not.toBe("school_admin");
  });

  it("shows a retryable error when the feedback queue fails instead of loading forever", async () => {
    apiMock.getFeedbackQueue
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({
        rows: [],
        total: 0,
        open_count: 0,
        limit: 20,
        offset: 0,
      });

    renderAdmin();
    await screen.findByText("Adm School");

    // The failure must be visible, not an endless "loading" state. Before the
    // fix this role never appeared: the queue stayed null and re-rendered
    // t("loading") forever. The AI-quality card now renders its own alert on
    // a failed fetch (FE-04), so match the text (plural) — both panels are
    // honestly reporting the same outage, which is the point.
    const alerts = await screen.findAllByText(t("errGeneric"));
    expect(alerts.length).toBeGreaterThan(0);

    fireEvent.click(
      screen.getByRole("button", {
        name: `${t("admTriage")} — ${t("retry")}`,
      }),
    );
    await waitFor(() =>
      expect(apiMock.getFeedbackQueue).toHaveBeenCalledTimes(2),
    );
    await waitFor(() =>
      expect(screen.getByText(t("admNoFeedback"))).toBeInTheDocument(),
    );
  });
});
