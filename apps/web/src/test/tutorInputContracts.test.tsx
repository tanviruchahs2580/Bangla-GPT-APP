/**
 * The tutor composer's input contracts.
 *
 * FE-FIX-016: `ChatSendRequest.message` is 3–1000 characters (the API's own
 * schema), and nothing checked it client-side — "ki", a perfectly normal short
 * Banglish question, left the client, 422'd, and came back as the generic
 * "কিছু একটা সমস্যা হয়েছে", naming neither the field nor the rule. The check is
 * local now, the input survives it, and no request is spent on it.
 *
 * FE-FIX-015: `setInput("")` ran before the conversation POST, so a failed
 * create destroyed the typed question while the attached IMAGE was deliberately
 * kept (see the same function). The text is restored on failure, and never
 * clobbers anything typed since.
 *
 * FE-FIX-013: on an Android IME, Enter also confirms a Bangla composition. The
 * Enter handlers now check `isComposing`, so the keystroke that finishes a word
 * no longer sends it half-written.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import AITutorPage from "../pages/student/AITutorPage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  createNote: vi.fn(),
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

const CONV = { id: 9, title: "Chat", created_at: null, message_count: 0 };

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AITutorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function composer(): HTMLInputElement {
  // The generic form, not a post-hoc `as`: getByPlaceholderText is typed on the
  // element it resolves, so the assertion was redundant — and the lint rule
  // that flags redundant assertions is right to say so.
  return screen.getByPlaceholderText<HTMLInputElement>(t("askPlaceholder"));
}

beforeEach(() => {
  vi.clearAllMocks();
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
  apiMock.get.mockResolvedValue([]);
  apiMock.post.mockResolvedValue(CONV);
  apiMock.postStream.mockResolvedValue({
    message_id: 1,
    grounded: true,
    sources: [],
  });
});

describe("question length validation", () => {
  it("refuses a too-short question locally, keeps the text, and spends no request", async () => {
    renderPage();
    const box = await screen.findByPlaceholderText(t("askPlaceholder"));
    fireEvent.change(box, { target: { value: "ki" } });
    fireEvent.keyDown(box, { key: "Enter" });

    expect(await screen.findByText(t("questionTooShort"))).toBeTruthy();
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(composer().value).toBe("ki");
  });

  it("asks a valid question", async () => {
    renderPage();
    const box = await screen.findByPlaceholderText(t("askPlaceholder"));
    fireEvent.change(box, { target: { value: "সালোকসংশ্লেষণ কীভাবে কাজ করে?" } });
    fireEvent.keyDown(box, { key: "Enter" });

    await waitFor(() => expect(apiMock.post).toHaveBeenCalled());
    expect(
      apiMock.post.mock.calls.some(([url]) => String(url).includes("/tutor/")),
    ).toBe(true);
  });
});

describe("IME composition", () => {
  it("does not send on the Enter that confirms a Bangla composition", async () => {
    renderPage();
    const box = await screen.findByPlaceholderText(t("askPlaceholder"));
    fireEvent.change(box, { target: { value: "কোষ কী" } });
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });

    // Nothing was sent and the half-composed question is still in the box.
    await new Promise((r) => setTimeout(r, 30));
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(apiMock.postStream).not.toHaveBeenCalled();
    expect(composer().value).toBe("কোষ কী");
    expect(screen.queryByText(t("questionTooShort"))).toBeNull();
  });

  it("still sends on a real Enter", async () => {
    renderPage();
    const box = await screen.findByPlaceholderText(t("askPlaceholder"));
    fireEvent.change(box, { target: { value: "কোষ কী" } });
    fireEvent.keyDown(box, { key: "Enter", isComposing: false });
    await waitFor(() => expect(apiMock.post).toHaveBeenCalled());
  });
});

describe("failed conversation create", () => {
  it("gives the typed question back instead of destroying it", async () => {
    apiMock.post.mockRejectedValue(new Error("503"));
    renderPage();
    const box = await screen.findByPlaceholderText(t("askPlaceholder"));
    const question = "সালোকসংশ্লেষণ কীভাবে কাজ করে?";
    fireEvent.change(box, { target: { value: question } });
    fireEvent.keyDown(box, { key: "Enter" });

    expect(await screen.findByText(t("newChatFailed"))).toBeTruthy();
    // The text is back, so the retry does not begin by retyping the question.
    await waitFor(() => expect(composer().value).toBe(question));
    expect(apiMock.postStream).not.toHaveBeenCalled();
  });
});

describe("subject picker", () => {
  it("is a labelled group with a pressed state", async () => {
    renderPage();
    const group = await screen.findByRole("group", { name: t("subject") });
    const science = within(group).getByRole("button", {
      name: t("subjectScience"),
    });
    expect(science).toHaveAttribute("aria-pressed", "true");
    expect(
      within(group).getByRole("button", { name: t("subjectMath") }),
    ).toHaveAttribute("aria-pressed", "false");
  });
});
