/**
 * B-03: "logout invalidates server-side".
 *
 * The client stored the bearer token in localStorage, wiped it locally on
 * sign-out and never told the API. A copy of that token (a shared device's
 * browser history is not the only path: any logged request in a proxy log,
 * any XSS read) stayed valid until its 60-minute expiry, so "sign out" on a
 * school tablet did not end the session it claimed to end. The API exposes
 * POST /auth/logout (AUD-B-04) which retires the token's jti in the shared
 * revocation store; the client has to call it.
 *
 * The local wipe is not allowed to depend on the network: an offline tablet
 * must still sign out. These tests pin both halves.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { logout, setLogoutCleanup } from "../api";

interface Captured {
  url: string;
  method: string;
  authorization: string | null;
  tokenStillStored: boolean;
}

/** A fetch that records the logout request and answers 204. */
function recordingFetch(captured: Captured[], status = 204) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation((input: unknown, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      captured.push({
        url: String(input),
        method: init?.method ?? "GET",
        authorization: headers.get("Authorization"),
        tokenStillStored: localStorage.getItem("bgpt_token") !== null,
      });
      return Promise.resolve(new Response(null, { status }));
    });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  setLogoutCleanup(null);
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("logout retires the session server-side (B-03)", () => {
  it("posts the captured token to /auth/logout", async () => {
    localStorage.setItem("bgpt_token", "tok-abc");
    const captured: Captured[] = [];
    const fetchSpy = recordingFetch(captured);

    await logout();

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(captured[0].url).toContain("/auth/logout");
    expect(captured[0].method).toBe("POST");
    // The header is what the API revokes. The local wipe has already run (it
    // must, for a shared device), so the token has to be carried explicitly
    // rather than read back out of storage.
    expect(captured[0].authorization).toBe("Bearer tok-abc");
    expect(captured[0].tokenStillStored).toBe(false);
    expect(localStorage.getItem("bgpt_token")).toBeNull();
  });

  it("wipes the device synchronously, before the network is involved", () => {
    // F-036: the local wipe may not wait on a request. A caller that does not
    // await logout() (an unload handler, a crash path) must still leave a
    // clean device.
    localStorage.setItem("bgpt_token", "tok-abc");
    localStorage.setItem("lastChapter", "cell");
    localStorage.setItem("bgpt_admin_token_backup", "admin-tok");
    recordingFetch([]);

    const pending = logout();

    expect(localStorage.getItem("bgpt_token")).toBeNull();
    expect(localStorage.getItem("lastChapter")).toBeNull();
    expect(localStorage.getItem("bgpt_admin_token_backup")).toBeNull();
    return pending;
  });

  it("still signs out locally when the revoke call fails", async () => {
    localStorage.setItem("bgpt_token", "tok-abc");
    localStorage.setItem("lastChapter", "cell");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));

    await expect(logout()).resolves.toBeUndefined();

    expect(localStorage.getItem("bgpt_token")).toBeNull();
    expect(localStorage.getItem("lastChapter")).toBeNull();
  });

  it("treats a failed revoke (401 from an already-dead token) as signed out", async () => {
    localStorage.setItem("bgpt_token", "expired");
    const captured: Captured[] = [];
    recordingFetch(captured, 401);
    const handler = vi.fn();
    const { setUnauthorizedHandler } = await import("../api");
    setUnauthorizedHandler(handler);

    await expect(logout()).resolves.toBeUndefined();

    // The 401 must not bounce the user through the global re-login handler:
    // they are already signing out.
    expect(handler).not.toHaveBeenCalled();
    expect(localStorage.getItem("bgpt_token")).toBeNull();
    setUnauthorizedHandler(() => {});
  });

  it("makes no request when there is no token to revoke", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    await logout();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
