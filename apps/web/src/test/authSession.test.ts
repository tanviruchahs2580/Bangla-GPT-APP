import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchMe, getToken, login } from "../api";

const TOKEN =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwicm9sZSI6InN0dWRlbnQifQ.sig";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("auth session resilience (instant-logout fix)", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("login throws (instead of phantom success) when session verify fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: unknown) => {
      const url = String(input);
      if (url.endsWith("/auth/login")) {
        return Promise.resolve(jsonResponse({ access_token: TOKEN }));
      }
      return Promise.reject(new TypeError("network down"));
    });
    await expect(login("a@b.com", "longpassword1")).rejects.toMatchObject({
      code: "verify_failed",
    });
    // Transient failure must NOT wipe the freshly stored token.
    expect(getToken()).toBe(TOKEN);
  });

  it("fetchMe logs out only on 401, keeps token on transient errors", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    localStorage.setItem("bgpt_token", TOKEN);

    fetchSpy.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: "bad" }, 401)),
    );
    expect(await fetchMe()).toBeNull();
    expect(getToken()).toBeNull();

    localStorage.setItem("bgpt_token", TOKEN);
    fetchSpy.mockImplementation(() =>
      Promise.reject(new TypeError("network down")),
    );
    expect(await fetchMe()).toBeNull();
    expect(getToken()).toBe(TOKEN);
  });

  it("login succeeds end-to-end when verify passes", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: unknown) => {
      const url = String(input);
      if (url.endsWith("/auth/login")) {
        return Promise.resolve(jsonResponse({ access_token: TOKEN }));
      }
      return Promise.resolve(
        jsonResponse({ user_id: 1, email: "a@b.com", role: "student" }),
      );
    });
    await expect(login("a@b.com", "longpassword1")).resolves.toBe("student");
    expect(getToken()).toBe(TOKEN);
  });
});
