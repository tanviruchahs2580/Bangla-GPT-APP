/**
 * F-012: the tutor double-send race.
 *
 * `streaming` was only set after the conversation POST resolved, so a second
 * send during that round-trip passed the guard: it posted a second
 * conversation and started a second SSE stream, and `abortRef.current` was
 * overwritten so Stop could only kill the newer one.
 *
 * The fix is a synchronous ref guard plus ONE AbortController per turn that
 * covers the conversation POST and the stream.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const CONV = {
  id: 9,
  title: "Chat",
  created_at: null,
  message_count: 0,
};

function abortError(): Error {
  const e = new Error("aborted");
  e.name = "AbortError";
  return e;
}

/** Type + Enter in one act-friendly step (user.type per character is slow). */
function submit(box: HTMLElement, text: string) {
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
}

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
  apiMock.get.mockResolvedValue([]); // conversations list
});

describe("tutor send guard (F-012)", () => {
  // `post` also carries fire-and-forget analytics events; count only the
  // conversation creates.
  const convPosts = () =>
    apiMock.post.mock.calls.filter(([path]) => path === "/tutor/conversations");

  it("ignores a second send while the conversation POST is in flight", async () => {
    let resolvePost!: (v: unknown) => void;
    apiMock.post.mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve;
      }),
    );
    apiMock.postStream.mockResolvedValue({
      message_id: 5,
      grounded: true,
      sources: [],
      confidence: 0.9,
    });

    renderPage();
    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });

    submit(box, "Kosh ki?");
    await waitFor(() => expect(convPosts()).toHaveLength(1));

    // Second question while the conversation POST is still unresolved — the
    // old code fired a second conversation POST here.
    submit(box, "Arek proshno?");
    expect(convPosts()).toHaveLength(1);
    // The blocked send must not have eaten the typed text.
    expect((box as HTMLInputElement).value).toBe("Arek proshno?");

    resolvePost(CONV);
    await waitFor(() => expect(apiMock.postStream).toHaveBeenCalledTimes(1));
    // Exactly one turn ever started.
    expect(convPosts()).toHaveLength(1);
    expect(apiMock.postStream).toHaveBeenCalledTimes(1);
  }, 30000);

  it("Stop aborts the in-flight conversation POST", async () => {
    const user = userEvent.setup();
    let postSignal: AbortSignal | undefined;
    apiMock.post.mockImplementation(
      (_path: string, _body: unknown, opts?: { signal?: AbortSignal }) => {
        postSignal = opts?.signal;
        return new Promise((_res, reject) => {
          opts?.signal?.addEventListener("abort", () => reject(abortError()));
        });
      },
    );

    renderPage();
    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });
    submit(box, "Q1");

    // Stop must be available while the POST is in flight, not only once the
    // stream is running.
    const stop = await screen.findByRole("button", {
      name: t("stopGenerating"),
    });
    await user.click(stop);

    expect(postSignal?.aborted).toBe(true);
    expect(apiMock.postStream).not.toHaveBeenCalled();
    // The aborted turn unwinds and the send control returns.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: t("send") }),
      ).toBeInTheDocument(),
    );
  }, 30000);

  it("Stop aborts the in-flight stream", async () => {
    const user = userEvent.setup();
    apiMock.post.mockResolvedValue(CONV);
    let streamSignal: AbortSignal | undefined;
    apiMock.postStream.mockImplementation(
      (
        _path: string,
        _body: unknown,
        _onToken: (t: string) => void,
        opts?: { signal?: AbortSignal },
      ) => {
        streamSignal = opts?.signal;
        return new Promise((_res, reject) => {
          opts?.signal?.addEventListener("abort", () => reject(abortError()));
        });
      },
    );

    renderPage();
    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });
    submit(box, "Q1");

    await waitFor(() => expect(apiMock.postStream).toHaveBeenCalledTimes(1));
    const stop = screen.getByRole("button", { name: t("stopGenerating") });
    await user.click(stop);

    expect(streamSignal?.aborted).toBe(true);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: t("send") }),
      ).toBeInTheDocument(),
    );
  }, 30000);
});
