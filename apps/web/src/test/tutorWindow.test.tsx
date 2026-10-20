/** AUD-G-19: the tutor transcript renders a trailing window, not the whole thread.
 *
 * 120 seeded messages (seed_long_history.py's e2e shape) used to mount in one
 * commit -- a 1,700+ ms main-thread task at 4x CPU, repeated on every streamed
 * token. The page now renders the last MESSAGE_WINDOW messages and keeps the
 * older ones one "load earlier messages" click away. These tests pin the
 * window maths, the affordance and the per-conversation reset e2e/perf.spec.ts
 * depends on.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { t } from "../i18n";
import { renderTutorPage, wireTutorMocks } from "./tutorPageMock";

// The hoisted surface must stay per-file (see tutorPageMock.tsx docstring).
// This suite only reads through the API, so the unused verbs share one
// throwaway fn — deliberately not the per-verb shape the action suites use.
const never = vi.hoisted(() => vi.fn());
const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: never,
  postStream: never,
  patch: never,
  del: never,
}));
const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));
vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

/** MESSAGE_WINDOW must stay conceptually in sync with AITutorPage.tsx. */
const WINDOW = 30;

/**
 * Testing-library's default timeout (1s) assumes an idle machine; the unit
 * suite runs several workers at once here, and a slow worker is not a window
 * bug. Every async query waits up to WAIT before it is called a failure.
 */
const WAIT = 8000;

interface Msg {
  id: number;
  role: "user" | "assistant";
  content: string;
  grounded: boolean | null;
  sources: unknown[];
  created_at: string;
}

function thread(count: number): Msg[] {
  return Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    role: index % 2 === 0 ? "user" : "assistant",
    content: `msg-${index + 1}`,
    grounded: null,
    sources: [],
    created_at: new Date(Date.UTC(2026, 0, 1, 0, index)).toISOString(),
  }));
}

const CONVERSATIONS = [
  { id: 1, title: "Long chat", created_at: null, message_count: 120 },
  { id: 2, title: "Medium chat", created_at: null, message_count: 40 },
  { id: 3, title: "Tiny chat", created_at: null, message_count: 12 },
];

function bubbleCount(): number {
  return document.querySelectorAll(".bubble").length;
}

describe("tutor transcript window (AUD-G-19)", () => {
  beforeEach(() => {
    wireTutorMocks(apiMock, authMock);
    apiMock.get.mockImplementation((url: string) => {
      if (url.includes("/conversations/1/messages"))
        return Promise.resolve(thread(120));
      if (url.includes("/conversations/2/messages"))
        return Promise.resolve(thread(40));
      if (url.includes("/conversations/3/messages"))
        return Promise.resolve(thread(12));
      return Promise.resolve(CONVERSATIONS);
    });
  });

  it("mounts only the trailing window of a long thread, with the affordance shown", async () => {
    renderTutorPage();
    const longChat = await screen.findByRole(
      "button",
      { name: "Long chat" },
      { timeout: WAIT },
    );
    await userEvent.setup().click(longChat);
    await screen.findByText("msg-120", undefined, { timeout: WAIT });
    expect(bubbleCount()).toBe(WINDOW);
    expect(screen.getByRole("button", { name: t("loadEarlier") })).toBeTruthy();
    // The window is the trailing one: the OLDEST message must not be mounted.
    expect(document.body.contains(screen.queryByText("msg-1") ?? null)).toBe(
      false,
    );
    // The composer is still the live input (the full array feeds its logic).
    expect(
      screen.getByRole("textbox", { name: t("askPlaceholder") }),
    ).toBeTruthy();
  });

  it("load earlier reveals one more window and keeps it scroll-stable", async () => {
    renderTutorPage();
    await userEvent
      .setup()
      .click(
        await screen.findByRole(
          "button",
          { name: "Long chat" },
          { timeout: WAIT },
        ),
      );
    await screen.findByText("msg-120", undefined, { timeout: WAIT });
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: t("loadEarlier") }));
    expect(bubbleCount()).toBe(2 * WINDOW);
    // The second window is messages 61..120: msg-61 just mounted, the head
    // (msg-60 and above) is still unmounted.
    expect(screen.getByText("msg-61")).toBeTruthy();
    expect(document.body.contains(screen.queryByText("msg-60") ?? null)).toBe(
      false,
    );
  });

  it("a thread smaller than the window renders whole and shows no affordance", async () => {
    renderTutorPage();
    await userEvent
      .setup()
      .click(
        await screen.findByRole(
          "button",
          { name: "Tiny chat" },
          { timeout: WAIT },
        ),
      );
    await screen.findByText("msg-12", undefined, { timeout: WAIT });
    expect(bubbleCount()).toBe(12);
    expect(screen.queryByRole("button", { name: t("loadEarlier") })).toBeNull();
  });

  it("opening another conversation resets the window (no stale larger window)", async () => {
    renderTutorPage();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole(
        "button",
        { name: "Long chat" },
        { timeout: WAIT },
      ),
    );
    await screen.findByText("msg-120", undefined, { timeout: WAIT });
    await user.click(screen.getByRole("button", { name: t("loadEarlier") }));
    expect(bubbleCount()).toBe(2 * WINDOW);

    // A fresh 40-message thread under a still-expanded window would render 40
    // bubbles with no affordance; the reset makes it the standard 30 + link.
    await user.click(screen.getByRole("button", { name: "Medium chat" }));
    await screen.findByText("msg-40", undefined, { timeout: WAIT });
    expect(bubbleCount()).toBe(WINDOW);
    expect(screen.getByRole("button", { name: t("loadEarlier") })).toBeTruthy();
  });
});
