/**
 * FE-FIX-014: the chat viewport was force-scrolled to the bottom on every
 * state change, and the stream flushes every 80 ms — so a student who scrolled
 * up to re-read their question, or to look at the evidence behind a claim, was
 * dragged back down four times a second. It now follows the stream only while
 * the reader is already at the bottom, and it scrolls instantly (not smoothly)
 * when the reader has asked for reduced motion — a query this project already
 * honours in `lib/confetti.ts` and which the repeated smooth slide ignored.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

const VIEWPORT = ".chat-viewport";

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

/** jsdom reports 0 for every geometry property; give the viewport a real box. */
function setGeometry(
  el: HTMLElement,
  { scrollHeight, clientHeight, scrollTop }: Record<string, number>,
) {
  Object.defineProperty(el, "scrollHeight", {
    configurable: true,
    value: scrollHeight,
  });
  Object.defineProperty(el, "clientHeight", {
    configurable: true,
    value: clientHeight,
  });
  el.scrollTop = scrollTop;
}

async function sendTurn() {
  const box = await screen.findByPlaceholderText(t("askPlaceholder"));
  fireEvent.change(box, { target: { value: "সালোকসংশ্লেষণ কীভাবে কাজ করে?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  await waitFor(() => expect(apiMock.post).toHaveBeenCalled());
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
  apiMock.post.mockResolvedValue({
    id: 9,
    title: "Chat",
    created_at: null,
    message_count: 0,
  });
  let answer = 0;
  apiMock.postStream.mockImplementation(
    async (
      _url: string,
      _body: unknown,
      onToken: (t: string) => void,
    ): Promise<unknown> => {
      answer += 1;
      onToken(`উত্তর ${answer}`);
      return { message_id: answer, grounded: true, sources: [] };
    },
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("tutor viewport autoscroll", () => {
  it("follows the stream while the reader is at the bottom", async () => {
    const scrollTo = vi.spyOn(Element.prototype, "scrollTo");
    const { container } = renderPage();
    await sendTurn();

    await waitFor(() => expect(scrollTo).toHaveBeenCalled());
    const viewport = container.querySelector(VIEWPORT) as HTMLElement;
    // scrollTo takes one options object here, so the option is the first arg.
    const smooth = scrollTo.mock.calls.filter(
      ([opts]) => (opts as ScrollToOptions)?.behavior === "smooth",
    );
    expect(smooth.length).toBeGreaterThan(0);
    expect(viewport).toBeTruthy();
  });

  it("stops following once the reader scrolls up", async () => {
    const scrollTo = vi.spyOn(Element.prototype, "scrollTo");
    const { container } = renderPage();
    await sendTurn();
    await waitFor(() => expect(scrollTo).toHaveBeenCalled());

    const viewport = container.querySelector(VIEWPORT) as HTMLElement;
    // 1000 tall, 400 visible, scrolled to 100: the reader is 500 px from the
    // bottom, i.e. reading something older.
    setGeometry(viewport, {
      scrollHeight: 1000,
      clientHeight: 400,
      scrollTop: 100,
    });
    fireEvent.scroll(viewport);

    scrollTo.mockClear();
    await sendTurn();

    // A second turn lands without yanking the viewport back down.
    await waitFor(() => expect(apiMock.postStream).toHaveBeenCalledTimes(2));
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("scrolls instantly when the reader asked for reduced motion", async () => {
    // jsdom has no matchMedia at all, so the preference is stubbed rather
    // than spied: the component reads it through lib/motion.
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: () => ({
        matches: true,
        media: "(prefers-reduced-motion: reduce)",
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        onchange: null,
        dispatchEvent: () => false,
      }),
    });
    const scrollTo = vi.spyOn(Element.prototype, "scrollTo");

    renderPage();
    await sendTurn();

    await waitFor(() =>
      expect(
        scrollTo.mock.calls.some(
          ([opts]) => (opts as ScrollToOptions)?.behavior === "auto",
        ),
      ).toBe(true),
    );
    expect(
      scrollTo.mock.calls.some(
        ([opts]) => (opts as ScrollToOptions)?.behavior === "smooth",
      ),
    ).toBe(false);
  });
});
