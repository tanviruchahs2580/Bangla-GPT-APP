/** Funnel guard: analytics fires while logged out (welcome CTAs), so a 401
 * from /events must never trip the global unauthorized handler that
 * force-redirects to /login (that bounce destroys the register flow). */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setUnauthorizedHandler } from "../api";
import { track } from "../lib/analytics";

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
    track("welcome_cta", { cta: "register" });
    await new Promise((r) => setTimeout(r, 30));
    expect(fetchMock).toHaveBeenCalledOnce();
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
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("Unauthorized", { status: 401 })),
    );
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    try {
      track("welcome_cta", { cta: "login" });
      await new Promise((r) => setTimeout(r, 30));
      expect(handler).not.toHaveBeenCalled();
    } finally {
      setUnauthorizedHandler(() => {});
    }
  });
});
