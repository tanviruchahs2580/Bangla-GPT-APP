import { afterEach, describe, expect, it, vi } from "vitest";
import {
  apiTargetUrl,
  handleApiProxy,
  resolveApiOrigin,
} from "../lib/apiProxy";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("resolveApiOrigin", () => {
  it("returns the trimmed origin without trailing slashes", () => {
    expect(resolveApiOrigin({ API_ORIGIN: " https://api.example.com/ " })).toBe(
      "https://api.example.com",
    );
  });

  it("returns null when unset, empty, or scheme-less (honest 503 beats a malformed call)", () => {
    expect(resolveApiOrigin({})).toBeNull();
    expect(resolveApiOrigin({ API_ORIGIN: "   " })).toBeNull();
    expect(resolveApiOrigin({ API_ORIGIN: "api.example.com" })).toBeNull();
  });
});

describe("apiTargetUrl", () => {
  it("strips the /api prefix and keeps the query string", () => {
    expect(
      apiTargetUrl(
        "https://spa.vercel.app/api/health",
        "https://api.example.com",
      ),
    ).toBe("https://api.example.com/health");
    expect(
      apiTargetUrl(
        "https://spa.vercel.app/api/tutor/conversations/3/messages?limit=8",
        "https://api.example.com",
      ),
    ).toBe("https://api.example.com/tutor/conversations/3/messages?limit=8");
  });
});

describe("handleApiProxy", () => {
  it("answers 503 api_origin_unconfigured when API_ORIGIN is missing", async () => {
    const request = new Request("https://spa.vercel.app/api/health");
    const res = await handleApiProxy(request, {});
    expect(res.status).toBe(503);
    const body = (await res.json()) as { code: string };
    expect(body.code).toBe("api_origin_unconfigured");
  });

  it("forwards method, headers and body to the origin and relays the response", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json", "content-length": "14" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const request = new Request("https://spa.vercel.app/api/auth/login", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: "Bearer tok",
      },
      body: JSON.stringify({ email: "a@b.c", password: "x" }),
    });
    const res = await handleApiProxy(request, {
      API_ORIGIN: "https://api.example.com",
    });

    expect(res.status).toBe(200);
    expect((await res.json()) as { status: string }).toEqual({ status: "ok" });

    const [target, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(target).toBe("https://api.example.com/auth/login");
    expect(init.method).toBe("POST");
    const headers = new Headers(init.headers);
    expect(headers.get("authorization")).toBe("Bearer tok");
    expect(headers.get("host")).toBeNull();
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toContain(
      "a@b.c",
    );
  });

  it("strips client-supplied forwarding headers (rate-limit identity spoofing)", async () => {
    // A caller must not choose its own X-Forwarded-For: the API reads its
    // last entry as the caller identity when TRUST_PROXY_HEADERS=true, and an
    // appending proxy would let the spoofed value rotate the rate-limit key.
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const request = new Request("https://spa.vercel.app/api/auth/login", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-forwarded-for": "1.2.3.4, 5.6.7.8",
        "x-real-ip": "1.2.3.4",
        "x-forwarded-host": "evil.example",
      },
      body: "{}",
    });
    await handleApiProxy(request, { API_ORIGIN: "https://api.example.com" });

    const upstreamHeaders = new Headers(
      (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers,
    );
    expect(upstreamHeaders.get("x-forwarded-for")).toBeNull();
    expect(upstreamHeaders.get("x-real-ip")).toBeNull();
    expect(upstreamHeaders.get("x-forwarded-host")).toBeNull();
    expect(upstreamHeaders.get("content-type")).toBe("application/json");
  });

  it("never forwards hop-by-hop headers upstream or back", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response("streamed", {
        status: 200,
        headers: { "transfer-encoding": "chunked", "content-encoding": "gzip" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const request = new Request("https://spa.vercel.app/api/health", {
      headers: { connection: "keep-alive" },
    });
    const res = await handleApiProxy(request, {
      API_ORIGIN: "https://api.example.com",
    });

    const upstreamHeaders = new Headers(
      (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers,
    );
    expect(upstreamHeaders.get("connection")).toBeNull();
    expect(res.headers.get("transfer-encoding")).toBeNull();
    expect(res.headers.get("content-encoding")).toBeNull();
  });

  it("relays upstream error statuses untouched", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "nope" }), { status: 401 }),
      ),
    );
    const res = await handleApiProxy(
      new Request("https://spa.vercel.app/api/users/me"),
      { API_ORIGIN: "https://api.example.com" },
    );
    expect(res.status).toBe(401);
  });

  // A dead API_ORIGIN -- stopped container, expired tunnel, DNS failure --
  // used to reject out of the handler and surface as a bare 500 that named
  // neither the cause nor the host. That is exactly how production looked
  // healthy while every API call was failing.
  it("answers 502 api_origin_unreachable when the origin refuses the connection", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    const res = await handleApiProxy(
      new Request("https://spa.vercel.app/api/health"),
      {
        API_ORIGIN: "https://api.example.com",
      },
    );
    expect(res.status).toBe(502);
    const body = (await res.json()) as { code: string };
    expect(body.code).toBe("api_origin_unreachable");
  });

  it("does not disclose the origin host to the client", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    const res = await handleApiProxy(
      new Request("https://spa.vercel.app/api/health"),
      {
        API_ORIGIN: "https://internal-tunnel.trycloudflare.com",
      },
    );
    const text = await res.text();
    expect(text).not.toContain("trycloudflare.com");
    expect(text).not.toContain("api.example.com");
  });

  it("records the failing origin in the server log, where operators can see it", async () => {
    const errorLog = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    await handleApiProxy(
      new Request("https://spa.vercel.app/api/tutor/ask", { method: "POST" }),
      {
        API_ORIGIN: "https://internal-tunnel.trycloudflare.com",
      },
    );
    expect(errorLog).toHaveBeenCalledTimes(1);
    const logged = JSON.parse(String(errorLog.mock.calls[0][0])) as Record<
      string,
      unknown
    >;
    expect(logged.event).toBe("api_origin_unreachable");
    expect(logged.origin).toBe("https://internal-tunnel.trycloudflare.com");
    expect(logged.method).toBe("POST");
    expect(logged.path).toBe("/api/tutor/ask");
  });
});

describe("handleApiProxy upstream deadlines", () => {
  it("answers 502 api_origin_timeout when the origin never sends headers", async () => {
    vi.useFakeTimers();
    try {
      // A fetch that only settles when its signal aborts — the hung origin.
      const fetchMock = vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () =>
              reject(new DOMException("aborted", "AbortError")),
            );
          }),
      );
      vi.stubGlobal("fetch", fetchMock);

      const request = new Request("https://spa.vercel.app/api/health");
      const pending = handleApiProxy(request, {
        API_ORIGIN: "https://api.example.com",
      });
      await vi.advanceTimersByTimeAsync(20_000);
      const res = await pending;

      expect(res.status).toBe(502);
      const body = (await res.json()) as { code: string; message: string };
      // A stall the client can retry is NOT the "origin is down" message: the
      // UI shows errTimeout for this code, not the connection posture copy.
      expect(body.code).toBe("api_origin_timeout");
      expect(body.message).toContain("20");
    } finally {
      vi.useRealTimers();
    }
  });

  it("bounds a non-streaming body with a total deadline", async () => {
    vi.useFakeTimers();
    try {
      // Headers arrive; the body then never produces a byte.
      let sourceController: ReadableStreamDefaultController<Uint8Array> | null =
        null;
      const stuckBody = new ReadableStream<Uint8Array>({
        start(controller) {
          sourceController = controller;
        },
      });
      // The fetch itself resolves (headers arrived); the deadline then has to
      // stop the BODY. The mock models the runtime's abort as terminating the
      // upstream stream — the only observer that can prove the timer did it.
      const fetchMock = vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((resolve) => {
            init?.signal?.addEventListener("abort", () => {
              sourceController?.close();
            });
            resolve(
              new Response(stuckBody, {
                status: 200,
                headers: { "content-type": "application/json" },
              }),
            );
          }),
      );
      vi.stubGlobal("fetch", fetchMock);

      const request = new Request("https://spa.vercel.app/api/users/me");
      const res = await handleApiProxy(request, {
        API_ORIGIN: "https://api.example.com",
      });
      const reader = res.body!.getReader();
      let settled = false;
      const read = reader.read().then((result) => {
        settled = true;
        return result;
      });
      // Well before the deadline the body is still (correctly) open.
      await vi.advanceTimersByTimeAsync(30_000);
      await Promise.resolve();
      expect(settled).toBe(false);
      // Past it, the upstream stream is terminated instead of pinning the
      // edge invocation forever.
      await vi.advanceTimersByTimeAsync(31_000);
      const first = await read;
      expect(first.done).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not bound an SSE body: a long generation is a legitimate answer", async () => {
    vi.useFakeTimers();
    try {
      let push: ((chunk: Uint8Array) => void) | null = null;
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          push = (chunk) => controller.enqueue(chunk);
        },
      });
      const fetchMock = vi.fn(
        async () =>
          new Response(stream, {
            status: 200,
            headers: { "content-type": "text/event-stream" },
          }),
      );
      vi.stubGlobal("fetch", fetchMock);

      const request = new Request("https://spa.vercel.app/api/tutor/stream");
      const res = await handleApiProxy(request, {
        API_ORIGIN: "https://api.example.com",
      });
      expect(res.headers.get("content-type")).toContain("text/event-stream");
      const reader = res.body!.getReader();

      await vi.advanceTimersByTimeAsync(120_000);
      push!(new TextEncoder().encode("event: token\ndata: {}\n\n"));
      const first = await reader.read();
      expect(first.done).toBe(false);
      expect(new TextDecoder().decode(first.value)).toContain("event: token");
    } finally {
      vi.useRealTimers();
    }
  });
});
