/**
 * Funnel guard: analytics fires while logged out (welcome CTAs), so a 401
 * from /events must never trip the global unauthorized handler that
 * force-redirects to /login (that bounce destroys the register flow).
 *
 * Isolation: `lib/analytics` keeps a 2 s in-flight dedupe window in module
 * state, so two tests tracking the same event name inside one worker
 * interfere. Each test imports a fresh module graph instead of sharing one:
 * with `--sequence.shuffle` the shared map made the second `track` a silent
 * no-op and failed whichever test ran second (observed on 2026-10-29).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";

async function freshModules() {
  vi.resetModules();
  const api = await import("../api");
  const analytics = await import("../lib/analytics");
  return { ...api, ...analytics };
}

describe("analytics funnel guard", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("posts the event payload to /events", async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { track } = await freshModules();
    track("welcome_cta", { cta: "register" });
    // Wait on the signal, not a wall-clock sleep: 30 ms was not enough when the
    // suite ran shuffled and loaded (measured 1 failure in 3 shuffled runs on
    // 2026-10-29), and waitFor keeps the assertion just as strong.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe("/api/events");
    expect(JSON.parse(init.body as string)).toEqual({
      name: "welcome_cta",
      props: { cta: "register" },
    });
  });

  it("a 401 from /events does not fire the unauthorized handler", async () => {
    const fetchMock = vi.fn(
      async () => new Response("Unauthorized", { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const handler = vi.fn();
    const { track, setUnauthorizedHandler } = await freshModules();
    setUnauthorizedHandler(handler);
    try {
      track("welcome_cta", { cta: "login" });
      await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
      expect(handler).not.toHaveBeenCalled();
    } finally {
      setUnauthorizedHandler(() => {});
    }
  });
});
