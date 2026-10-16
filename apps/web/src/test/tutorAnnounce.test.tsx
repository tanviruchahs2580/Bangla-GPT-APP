/**
 * F-016 / F-064: the transcript was itself an `aria-live="polite"` region, so
 * every streamed token was announced as it arrived. The chat now announces a
 * single time — politely — when the assistant's answer completes, and the
 * transcript carries no live semantics of its own.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
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

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

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

const CONV = { id: 9, title: "Chat", created_at: null, message_count: 0 };
const ANSWER = "কোষ হল জীবনের একক।";

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

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
  apiMock.get.mockResolvedValue([]);
  apiMock.post.mockResolvedValue(CONV);
  // Three chunks, like a real stream — the announcer must NOT update per chunk.
  apiMock.postStream.mockImplementation(
    async (_path: string, _body: unknown, onToken: (tok: string) => void) => {
      onToken("কোষ হল ");
      onToken("জীবনের ");
      onToken("একক।");
      return { message_id: 42, grounded: true, sources: [], confidence: 0.9 };
    },
  );
});

describe("tutor stream announcements (F-016)", () => {
  /** Type + Enter in one act-friendly step (per-character typing is slow). */
  function submit(box: HTMLElement, text: string) {
    fireEvent.change(box, { target: { value: text } });
    fireEvent.keyDown(box, { key: "Enter" });
  }

  it("announces the completed answer once instead of per token", async () => {
    renderPage();

    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });
    submit(box, "কোষ কী?");

    const announcer = await screen.findByTestId("tutor-announcer");
    await waitFor(() => expect(announcer).toHaveTextContent(ANSWER));
    // The live region is the dedicated announcer; the transcript itself must
    // not be a live region (that is what produced per-token announcements).
    expect(announcer).toHaveAttribute("aria-live", "polite");
    const thread = document.querySelector(".chat-viewport");
    expect(thread).not.toBeNull();
    expect(thread).not.toHaveAttribute("aria-live");
  }, 30000);

  it("does not announce anything before the answer completes", async () => {
    // A stream that never finishes: the announcer must stay empty (the old
    // transcript region announced every token while streaming).
    let onToken: ((tok: string) => void) | undefined;
    apiMock.postStream.mockImplementation(
      (_path: string, _body: unknown, tok: (t: string) => void) => {
        onToken = tok;
        return new Promise(() => {});
      },
    );
    renderPage();

    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });
    submit(box, "Q1");
    await waitFor(() => expect(onToken).toBeDefined());
    await act(async () => {
      onToken?.("আংশিক উত্তর");
    });

    const announcer = screen.getByTestId("tutor-announcer");
    expect(announcer.textContent).toBe("");
  }, 30000);
});
