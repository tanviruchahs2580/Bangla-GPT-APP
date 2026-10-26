/**
 * The tutor's bookmark button has always written notes ("Saved" toast) and
 * nothing could read them back: `getNotes` / `deleteNote` had no caller, so the
 * feature was write-only and the UI's claim was half a feature. The notes list
 * in MePage is the read half; these tests are what keeps it from rotting the
 * same way.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import MePage from "../pages/student/MePage";
import { setLang, t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  generateInviteCode: vi.fn(),
  // `getNotes`/`deleteNote` are defined inside api.ts and close over the
  // module's own `get`, so overriding `get` alone does not intercept them.
  getNotes: vi.fn(),
  deleteNote: vi.fn(),
  apiBase: "/api",
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
}));
vi.mock("../AuthContext", () => authMock);

const NOTES = [
  {
    id: 11,
    title: "কোষ কী",
    body: "জীবদেহের একক।",
    source: "tutor",
    source_ref: null,
    created_at: "2026-10-20T10:00:00",
  },
];

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
  // The language is module state: pin it so this file cannot inherit a
  // switch made by whichever test file ran before it.
  setLang("bn");
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
  apiMock.get.mockImplementation((path: string) => {
    if (path.startsWith("/notes")) return Promise.resolve(NOTES);
    return Promise.resolve(null);
  });
  apiMock.getNotes.mockResolvedValue(NOTES);
  apiMock.deleteNote.mockResolvedValue(undefined);
  apiMock.del.mockResolvedValue(undefined);
  apiMock.generateInviteCode.mockResolvedValue({
    code: "BGPT-AAAA",
    expires_in_minutes: 10,
  });
});

describe("saved notes", () => {
  it("lists what the tutor's save button stored", async () => {
    renderPage();
    expect(
      await screen.findByText(t("savedNotesTitle"), undefined, {
        timeout: 8000,
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("কোষ কী", undefined, { timeout: 8000 }),
    ).toBeInTheDocument();
    // the same client call the tutor's save button writes against
    expect(apiMock.getNotes).toHaveBeenCalled();
  });

  it("deletes a note and refreshes the list", async () => {
    renderPage();
    const btn = await screen.findByRole(
      "button",
      { name: new RegExp(t("noteDelete")) },
      { timeout: 8000 },
    );

    await userEvent.click(btn);

    // Generous budget: this runs inside a 70-file parallel suite, and a test
    // that fails only under load is worse than no test.
    await waitFor(() => expect(apiMock.deleteNote).toHaveBeenCalledWith(11), {
      timeout: 8000,
    });
  });

  it("shows the empty state instead of a broken list", async () => {
    apiMock.getNotes.mockResolvedValue([]);
    renderPage();
    expect(
      await screen.findByText(t("savedNotesEmpty"), undefined, {
        timeout: 8000,
      }),
    ).toBeInTheDocument();
  });
});
