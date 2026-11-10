/**
 * UX-006 / UX-002 on the tutor surface.
 *
 * UX-006: the stream rendered TWO assistant bubbles — the bubble that grows
 * with the answer (carrying a stream cursor) and, below it, a second empty
 * "AI" bubble with typing dots — for the whole duration of every turn. The
 * dots are now a suffix of the growing bubble, and the placeholder bubble is
 * only rendered while there is no bubble to grow into yet (the window
 * between "send" and the first token).
 *
 * UX-002: starting a stream is announced once, politely. The announcer that
 * carries the completed answer must stay empty until it completes
 * (tutorAnnounce.test.tsx pins that), so the start status is its own region
 * that exists only while a turn is streaming.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AITutorPage from "../pages/student/AITutorPage";
import { t } from "../i18n";
import type { ChatDoneEvent } from "../types";

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

const me = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "S",
  class_level: 6,
};

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

/** type + Enter in one act-friendly step (per-character typing is slow). */
function submit(box: HTMLElement, text: string) {
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
}

/** A stream the test drives token by token. */
function controlledStream() {
  const control: {
    push?: (tok: string) => void;
    finish?: () => void;
  } = {};
  apiMock.postStream.mockImplementation(
    (
      _path: string,
      _body: unknown,
      onToken: (tok: string) => void,
    ): Promise<ChatDoneEvent> =>
      new Promise((resolve) => {
        control.push = onToken;
        control.finish = () =>
          resolve({
            user_message_id: 41,
            message_id: 42,
            // The server echoes the assembled answer with the done event; the
            // page keeps its own accumulation, so this only has to be a
            // complete ChatDoneEvent.
            answer: "সম্পূর্ণ উত্তর",
            grounded: true,
            sources: [],
            confidence: 0.9,
          });
      }),
  );
  return control;
}

const bubbles = () => document.querySelectorAll(".bubble.assistant");

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
  apiMock.get.mockResolvedValue([]);
  apiMock.post.mockResolvedValue(CONV);
});

describe("one assistant bubble per turn (UX-006)", () => {
  it("grows the dots into the streaming bubble instead of a second one", async () => {
    const stream = controlledStream();
    renderPage();
    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });
    submit(box, "কোষ কী?");

    // Nothing to grow into yet: the placeholder is the only bubble, and it
    // is the one carrying the dots.
    await waitFor(() => expect(stream.push).toBeDefined());
    await waitFor(() => expect(bubbles()).toHaveLength(1));
    expect(bubbles()[0].querySelector(".typing-dots")).not.toBeNull();

    // First token: the bubble grows — text and dots in the SAME bubble.
    await act(async () => {
      stream.push?.("আংশিক উত্তর");
    });
    await waitFor(() => expect(bubbles()[0]).toHaveTextContent("আংশিক উত্তর"));
    expect(bubbles()).toHaveLength(1);
    expect(bubbles()[0].querySelector(".typing-dots")).not.toBeNull();
    expect(bubbles()[0].querySelector(".stream-cursor")).not.toBeNull();

    // Completed: one bubble, no wait indicator, and the answer intact.
    await act(async () => {
      stream.finish?.();
    });
    await waitFor(() => expect(bubbles()).toHaveLength(1));
    expect(bubbles()[0]).toHaveTextContent("আংশিক উত্তর");
    expect(document.querySelector(".typing-dots")).toBeNull();
    expect(document.querySelector(".stream-cursor")).toBeNull();
  });

  it("keeps a user turn from rendering an assistant bubble with it", async () => {
    const stream = controlledStream();
    renderPage();
    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });
    submit(box, "কোষ কী?");

    await waitFor(() => expect(stream.push).toBeDefined());
    // The student's own words are a user bubble; the only assistant bubble
    // is the pending one, and it holds no answer text.
    expect(document.querySelectorAll(".bubble.user")).toHaveLength(1);
    expect(bubbles()).toHaveLength(1);
    expect(bubbles()[0]).toHaveTextContent(t("thinking"));

    await act(async () => {
      stream.push?.("উত্তর");
      stream.finish?.();
    });
    await waitFor(() => expect(bubbles()).toHaveLength(1));
  });
});

describe("stream start status (UX-002)", () => {
  it("announces the start once, then leaves the completed answer to the announcer", async () => {
    const stream = controlledStream();
    renderPage();
    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });
    submit(box, "কোষ কী?");

    await waitFor(() => expect(stream.push).toBeDefined());
    const status = await screen.findByTestId("tutor-stream-status");
    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent(t("generatingAnswer"));
    // The completion announcer is untouched while the answer is still
    // arriving: no per-token chatter, and nothing announced twice.
    expect(screen.getByTestId("tutor-announcer").textContent).toBe("");

    await act(async () => {
      stream.push?.("সম্পূর্ণ উত্তর");
    });
    await waitFor(() =>
      expect(screen.getByTestId("tutor-stream-status")).toHaveTextContent(
        t("generatingAnswer"),
      ),
    );

    await act(async () => {
      stream.finish?.();
    });
    await waitFor(() =>
      expect(screen.queryByTestId("tutor-stream-status")).toBeNull(),
    );
    expect(screen.getByTestId("tutor-announcer")).toHaveTextContent(
      "সম্পূর্ণ উত্তর",
    );
  });
});
