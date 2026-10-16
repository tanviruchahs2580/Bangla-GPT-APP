/**
 * F-015 / F-030: no request had a timeout, so a proxy that accepted the
 * connection and then went silent hung the UI forever (a stalled GET left a
 * spinner; a stalled stream left the tutor in `streaming` until Stop).
 *
 * Non-streaming calls get a hard deadline; the SSE stream gets a
 * connect/first-byte deadline plus an inter-chunk stall deadline that resets
 * on every received chunk (a whole-stream deadline would kill long, healthy
 * generations). Timers are setTimeout-based so fake timers can drive them.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getBlob,
  post,
  postStream,
  REQUEST_TIMEOUT_MS,
  setUnauthorizedHandler,
  STREAM_CONNECT_TIMEOUT_MS,
  STREAM_STALL_TIMEOUT_MS,
} from "../api";
import { friendlyError } from "../errors";
import { t } from "../i18n";

function abortError(): Error {
  const e = new Error("aborted");
  e.name = "AbortError";
  return e;
}

/** A fetch that never answers until its signal aborts — a stalled connection. */
function stalledFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(
    (_input: unknown, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(abortError()));
      }),
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  setUnauthorizedHandler(() => {});
});

describe("non-streaming request timeout (F-015/F-030)", () => {
  it("rejects a stalled request with a machine-coded timeout error", async () => {
    stalledFetch();
    const p = post("/tutor/conversations", {});
    const assertion = expect(p).rejects.toMatchObject({
      status: 0,
      code: "timeout",
    });
    // Just short of the deadline: still pending.
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS - 1000);
    await vi.advanceTimersByTimeAsync(2000);
    await assertion;
    // A timeout has its own copy: "check your connection" would be wrong
    // advice when the connection is fine and the server is not answering.
    expect(friendlyError({ code: "timeout" }).text).toBe(t("errTimeout"));
  });

  it("forwards a caller abort signal so Stop can end a request (F-012)", async () => {
    let seen: AbortSignal | null | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input: unknown, init?: RequestInit) => {
        seen = init?.signal;
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(abortError()));
        });
      },
    );
    const caller = new AbortController();
    const p = post("/tutor/conversations", {}, { signal: caller.signal });
    expect(seen).toBeDefined();
    caller.abort();
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
  });

  it("clears the timeout after a successful response (no late abort)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(post("/tutor/conversations", {})).resolves.toEqual({
      ok: true,
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("SSE stream timeouts (F-015)", () => {
  it("times out a stream that never sends a first byte", async () => {
    stalledFetch();
    const p = postStream("/tutor/x/messages/stream", {}, () => {});
    const assertion = expect(p).rejects.toMatchObject({ code: "timeout" });
    await vi.advanceTimersByTimeAsync(STREAM_CONNECT_TIMEOUT_MS + 1);
    await assertion;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("resets the stall deadline on every chunk, so a long answer survives", async () => {
    const encoder = new TextEncoder();
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    const seen: string[] = [];
    const p = postStream<{ message_id: number }>(
      "/tutor/x/messages/stream",
      {},
      (tok) => seen.push(tok),
    );

    await vi.advanceTimersByTimeAsync(0); // fetch + first read parked
    controller.enqueue(encoder.encode('event: token\ndata: {"text":"ক"}\n\n'));
    await vi.advanceTimersByTimeAsync(0);

    // Three gaps of 40s each: cumulatively far past the 45s stall window, but
    // each individual gap is inside it — only a timer reset per chunk keeps
    // the stream alive.
    for (let i = 0; i < 3; i++) {
      await vi.advanceTimersByTimeAsync(STREAM_STALL_TIMEOUT_MS - 5000);
      controller.enqueue(
        encoder.encode('event: token\ndata: {"text":"খ"}\n\n'),
      );
      await vi.advanceTimersByTimeAsync(0);
    }

    controller.enqueue(
      encoder.encode('event: done\ndata: {"message_id":7}\n\n'),
    );
    controller.close();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(0);

    await expect(p).resolves.toMatchObject({ message_id: 7 });
    expect(seen.join("")).toBe("ক" + "খ".repeat(3));
    expect(vi.getTimerCount()).toBe(0);
  });

  it("rejects with a timeout when chunks stop arriving", async () => {
    const encoder = new TextEncoder();
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    const p = postStream("/tutor/x/messages/stream", {}, () => {});
    const assertion = expect(p).rejects.toMatchObject({ code: "timeout" });
    await vi.advanceTimersByTimeAsync(0);
    controller.enqueue(encoder.encode('event: token\ndata: {"text":"ক"}\n\n'));
    await vi.advanceTimersByTimeAsync(0);
    // Chunk received, then the stream goes silent past the stall window.
    await vi.advanceTimersByTimeAsync(STREAM_STALL_TIMEOUT_MS + 1);
    await assertion;
  });
});

describe("shared download client (F-021/F-032)", () => {
  it("routes a 401 through the global unauthorized handler like every other call", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code: "token_expired", message: "expired" },
        }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      ),
    );
    // The raw fetch this replaced never fired the handler, so an expired
    // session in the review panel just showed a generic error.
    await expect(
      getBlob("/teacher/qpapers/1/pdf?kind=paper"),
    ).rejects.toMatchObject({ status: 401, code: "token_expired" });
    expect(handler).toHaveBeenCalledTimes(1);
  });
});
