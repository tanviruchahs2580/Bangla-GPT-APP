import { afterEach, describe, expect, it, vi } from "vitest";
import { apiTargetUrl, handleApiProxy, resolveApiOrigin } from "../lib/apiProxy";

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
    expect(apiTargetUrl("https://spa.vercel.app/api/health", "https://api.example.com")).toBe(
      "https://api.example.com/health",
    );
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
      headers: { "content-type": "application/json", authorization: "Bearer tok" },
      body: JSON.stringify({ email: "a@b.c", password: "x" }),
    });
    const res = await handleApiProxy(request, { API_ORIGIN: "https://api.example.com" });

    expect(res.status).toBe(200);
    expect((await res.json()) as { status: string }).toEqual({ status: "ok" });

    const [target, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(target).toBe("https://api.example.com/auth/login");
    expect(init.method).toBe("POST");
    const headers = new Headers(init.headers);
    expect(headers.get("authorization")).toBe("Bearer tok");
    expect(headers.get("host")).toBeNull();
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toContain("a@b.c");
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
    const res = await handleApiProxy(request, { API_ORIGIN: "https://api.example.com" });

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
      vi.fn(async () => new Response(JSON.stringify({ detail: "nope" }), { status: 401 })),
    );
    const res = await handleApiProxy(
      new Request("https://spa.vercel.app/api/users/me"),
      { API_ORIGIN: "https://api.example.com" },
    );
    expect(res.status).toBe(401);
  });
});
