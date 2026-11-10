/**
 * UX-005: the Assessments page rendered `role="tablist"` with three
 * `role="tab"` buttons and implemented none of the keyboard contract that
 * role promises — no roving tabIndex, no Arrow/Home/End handling, and no
 * `aria-controls` pointing at a tabpanel (no element in the file carries
 * `role="tabpanel"`). The page's three controls are URL filters, so they now
 * use the shared Segmented control (components/ui.tsx documents exactly this
 * case): a `role="group"` of native buttons with `aria-pressed`.
 *
 * The contract pinned here is the one the widget actually promises: every
 * stop is a native button, reachable with Tab alone, and Enter/Space both
 * switch the panel — no role that claims more than that.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AssessmentsPage from "../pages/teacher/AssessmentsPage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/teacher/assessments?tab=papers"]}>
        <Routes>
          <Route path="/teacher/assessments" element={<AssessmentsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/teacher/classrooms") return Promise.resolve([]);
    if (path === "/teacher/qpapers") return Promise.resolve([]);
    if (path === "/teacher/shorttests") return Promise.resolve([]);
    if (path === "/teacher/assignments") return Promise.resolve([]);
    return Promise.resolve(null);
  });
});

afterEach(() => cleanup());

describe("assessments tab controls (UX-005)", () => {
  it("promises no tab semantics it does not implement", async () => {
    renderPage();

    // One filter group, three toggles — and no role="tab"/tablist left, so
    // no assistive technology is told to expect arrow traversal, a roving
    // tab stop or a tabpanel association that does not exist.
    const group = await screen.findByRole("group", { name: t("asmTitle") });
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.queryByRole("tablist")).toBeNull();

    const tabs = [
      t("asmTabPapers"),
      t("asmTabShortTests"),
      t("asmTabAssignments"),
    ];
    for (const label of tabs) {
      const toggle = within(group, label);
      await waitFor(() => expect(toggle).toBeInTheDocument());
    }
  });

  it("reaches every toggle with Tab and switches the panel with Enter", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(t("asmCreateInCreate"));

    const group = screen.getByRole("group", { name: t("asmTitle") });
    const shortTests = within(group, t("asmTabShortTests"));
    expect(shortTests).toHaveAttribute("aria-pressed", "false");

    // Tab traversal, not a roving tab stop: three presses reach the third
    // control from the first.
    within(group, t("asmTabPapers")).focus();
    await user.tab();
    expect(shortTests).toHaveFocus();

    // Enter activates the native button the same way a click does.
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(within(group, t("asmTabShortTests"))).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    // The panel under it really did change.
    expect(await screen.findByText(t("stEmpty"))).toBeInTheDocument();

    // Space reaches the third toggle and opens the bulk-assignment panel
    // (its chapter field, not its title: the title is the same string as
    // the toggle's own label).
    await user.tab();
    await user.keyboard(" ");
    await waitFor(() =>
      expect(within(group, t("asmTabAssignments"))).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(
      await screen.findByLabelText(t("baChapterLabel")),
    ).toBeInTheDocument();
  });
});

/** The button inside the filter group whose accessible name is `label`. */
function within(group: HTMLElement, label: string): HTMLElement {
  const button = Array.from(group.querySelectorAll("button")).find(
    (b) => b.textContent?.trim() === label,
  );
  if (!button) throw new Error(`no toggle labelled ${label}`);
  return button;
}
