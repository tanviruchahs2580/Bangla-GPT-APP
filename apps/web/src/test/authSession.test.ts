import { asText } from "../lib/text";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchMe, getToken, login, mfaChallenge } from "../api";

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
    // F-107: a connectivity failure now has its own code, so the UI can say
    // "the server is unreachable" rather than the generic failure.
    await expect(login("a@b.com", "longpassword1")).rejects.toMatchObject({
      code: "verify_unreachable",
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
    // F-107: the outcome is now a three-way discriminated result rather
    // than `MeResponse | null`, so "outage" cannot be mistaken for
    // "signed out" by the caller.
    expect(await fetchMe()).toEqual({ status: "unauthenticated" });
    expect(getToken()).toBeNull();

    localStorage.setItem("bgpt_token", TOKEN);
    fetchSpy.mockImplementation(() =>
      Promise.reject(new TypeError("network down")),
    );
    expect(await fetchMe()).toEqual({ status: "unreachable" });
    expect(getToken()).toBe(TOKEN);
  });

  it("a 429 on the session probe keeps the session instead of revoking it", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input: unknown) => {
        if (asText(input).endsWith("/auth/logout")) {
          return Promise.resolve(jsonResponse({}, 204));
        }
        return Promise.resolve(
          jsonResponse({ detail: { code: "rate_limited" } }, 429),
        );
      });
    localStorage.setItem("bgpt_token", TOKEN);

    // The per-user bound on GET /users/me (10/min) is a throttle, not an
    // authentication verdict: the token must survive, and the app must not
    // call the revoke endpoint on the way out.
    expect(await fetchMe()).toEqual({ status: "unreachable" });
    expect(getToken()).toBe(TOKEN);
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        asText(input).endsWith("/auth/logout"),
      ),
    ).toBe(false);
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
    // login() returns the verified profile so callers seed auth state
    // without a second /users/me round-trip.
    await expect(login("a@b.com", "longpassword1")).resolves.toMatchObject({
      me: { user_id: 1, role: "student" },
      mustChangePassword: false,
    });
    expect(getToken()).toBe(TOKEN);
  });

  it("login surfaces mfa_required (never a phantom session) for MFA accounts", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input: unknown) => {
        const url = String(input);
        if (url.endsWith("/auth/login")) {
          return Promise.resolve(
            jsonResponse({ access_token: "step-up-token", token_type: "mfa" }),
          );
        }
        return Promise.resolve(
          jsonResponse({ user_id: 1, email: "a@b.com", role: "student" }),
        );
      });
    await expect(login("a@b.com", "longpassword1")).rejects.toMatchObject({
      code: "mfa_required",
      status: 202,
    });
    // The step-up token must NOT become a session, and /users/me must
    // never be called with it (the server 401s mfa tokens).
    expect(getToken()).toBeNull();
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        asText(input).endsWith("/users/me"),
      ),
    ).toBe(false);
  });

  it("mfaChallenge exchanges the step-up token for a real session", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: unknown) => {
      const url = String(input);
      if (url.endsWith("/auth/mfa/challenge")) {
        return Promise.resolve(jsonResponse({ access_token: TOKEN }));
      }
      return Promise.resolve(
        jsonResponse({ user_id: 1, email: "a@b.com", role: "student" }),
      );
    });
    await expect(
      mfaChallenge("step-up-token", "123456"),
    ).resolves.toMatchObject({
      me: { user_id: 1, role: "student" },
      mustChangePassword: false,
    });
    expect(getToken()).toBe(TOKEN);
  });
});
