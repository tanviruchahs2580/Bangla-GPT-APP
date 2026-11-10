/**
 * FE-FIX-003 / FE-FIX-009 on the student's own page.
 *
 * FE-FIX-003: the learning-preference fetch failure was invisible. The inputs
 * rendered the module defaults as if they were the student's stored choices,
 * and Save posted those defaults back — silently overwriting real preferences.
 * The form now renders only over preferences that were actually read.
 *
 * FE-FIX-009: `removeNote` and `wipeMemory` (the "what the tutor remembers"
 * consent control) both ended in an empty catch, so a failed delete and a
 * failed wipe looked exactly like successes. Both use the toast convention the
 * tutor page already established for the same class of failure.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MePage from "../pages/student/MePage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  clearMyMemory: vi.fn(),
  getMyMemory: vi.fn(),
  getMyPrefs: vi.fn(),
  getMyReport: vi.fn(),
  patchMyPrefs: vi.fn(),
  revokeAllSessions: vi.fn(),
  deleteNote: vi.fn(),
  getNotes: vi.fn(),
  generateInviteCode: vi.fn(),
  apiBase: "/api",
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

// `importOriginal` so the module keeps its real surface — MePage renders
// ParentInviteCard, which uses a wrapper this file does not care about.
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
}));
vi.mock("../AuthContext", () => authMock);

const ACTIVITY = {
  streak: 2,
  today: "2026-11-10",
  days: [{ date: "2026-11-10", questions: 1, quizzes: 0, minutes: 3 }],
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

beforeEach(() => {
  vi.clearAllMocks();
  document.querySelectorAll(".toast-region").forEach((el) => el.remove());
  authMock.useAuth.mockReturnValue({
    me: {
      user_id: 1,
      email: "s@x.com",
      role: "student",
      profile_id: 7,
      name: "S",
      class_level: 6,
    },
    signOut: vi.fn(),
  });
  apiMock.get.mockResolvedValue(ACTIVITY);
  apiMock.getMyMemory.mockResolvedValue({
    memory_enabled: true,
    facts: { name: "S" },
    on_disable_note_code: null,
  });
  apiMock.getNotes.mockResolvedValue([
    { id: 5, title: "নোট", body: "body", created_at: "2026-11-01T10:00:00" },
  ]);
  apiMock.getMyReport.mockResolvedValue(null);
});

describe("learning preferences", () => {
  it("refuses to render a Save over preferences that were never read", async () => {
    apiMock.getMyPrefs.mockRejectedValue(new Error("503"));
    renderPage();

    expect(await screen.findByText(t("prefsLoadFailed"))).toBeTruthy();
    // The destructive path is unreachable: no form, no Save, no patch.
    expect(screen.queryByRole("button", { name: t("save") })).toBeNull();
    expect(screen.queryByLabelText(t("explanationStyle"))).toBeNull();
    expect(apiMock.patchMyPrefs).not.toHaveBeenCalled();
  });

  it("retries and then shows the student's stored preferences", async () => {
    const user = userEvent.setup();
    apiMock.getMyPrefs.mockRejectedValueOnce(new Error("503"));
    renderPage();
    await screen.findByText(t("prefsLoadFailed"));

    apiMock.getMyPrefs.mockResolvedValue({
      memory_enabled: true,
      learning_prefs: { explanation_style: "detailed", subject_focus: "গণিত" },
    });
    await user.click(screen.getByRole("button", { name: t("retry") }));

    await waitFor(() =>
      expect(screen.getByLabelText(t("explanationStyle"))).toBeTruthy(),
    );
    expect(screen.getByLabelText(t("explanationStyle"))).toHaveValue("detailed");
    expect(screen.getByLabelText(t("subjectFocus"))).toHaveValue("গণিত");
  });
});

describe("mutation failures are said out loud", () => {
  it("tells the student a failed note delete did not land", async () => {
    const user = userEvent.setup();
    apiMock.deleteNote.mockRejectedValue(new Error("500"));
    renderPage();

    await user.click(
      await screen.findByRole("button", {
        name: new RegExp(t("noteDelete")),
      }),
    );
    expect(await screen.findByText(t("errorGeneric"))).toBeTruthy();
  });

  it("tells the student a failed memory wipe did not land", async () => {
    const user = userEvent.setup();
    apiMock.clearMyMemory.mockRejectedValue(new Error("500"));
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: t("clearMemory") }),
    );
    expect(await screen.findByText(t("errorGeneric"))).toBeTruthy();
  });
});

// FE-FIX (numerals): the class badge is a quantity inside Bangla copy.
describe("profile numerals", () => {
  it("prints the class level in Bangla digits", async () => {
    apiMock.getMyPrefs.mockResolvedValue({
      memory_enabled: true,
      learning_prefs: { explanation_style: "standard", subject_focus: null },
    });
    renderPage();

    expect(await screen.findByText("শ্রেণি ৬")).toBeTruthy();
    expect(screen.queryByText("শ্রেণি 6")).toBeNull();
  });
});
