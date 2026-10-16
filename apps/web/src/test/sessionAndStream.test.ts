/**
 * Session-credential hygiene and SSE streaming robustness.
 *
 * SEC-006: `logout()` removed only `bgpt_token`. The admin token parked by
 *   `startImpersonation` (a full-power JWT) and the `bgpt_impersonating`
 *   flag survived, so a shared device handed the next user both an admin
 *   bearer token and an "acting as <student>" banner.
 *
 * BUG-004: `postStream` bypassed `api()`, so it never fired the global 401
 *   handler and reported every failure as a generic outage.
 *
 * BUG-005: `parseSse` never cleared the event name between frames and
 *   returned `null` when the stream ended without a terminal `done` frame,
 *   which callers dereferenced.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getToken,
  isImpersonating,
  logout,
  postStream,
  startImpersonation,
} from "../api";

const TOKEN = "student.jwt.token";
const ADMIN_TOKEN = "admin.jwt.token";
const IMPERSONATED = "impersonated.jwt.token";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("impersonation credentials", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });
  afterEach(() => {
    localStorage.clear();
  });

  it("startImpersonation parks the admin token and flags the session", async () => {
    localStorage.setItem("bgpt_token", ADMIN_TOKEN);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        access_token: IMPERSONATED,
        user_id: 7,
        role: "student",
        expires_in_min: 15,
      }),
    );
    const out = await startImpersonation(7, "support call");
    expect(out.user_id).toBe(7);
    expect(getToken()).toBe(IMPERSONATED);
    expect(isImpersonating()).toBe(true);
  });

  it("logout drops the parked admin token too, not just the session token", () => {
    localStorage.setItem("bgpt_token", IMPERSONATED);
    localStorage.setItem("bgpt_admin_token_backup", ADMIN_TOKEN);
    localStorage.setItem("bgpt_impersonating", "7");

    logout();

    expect(getToken()).toBeNull();
    // The regression: both of these used to survive logout().
    expect(localStorage.getItem("bgpt_admin_token_backup")).toBeNull();
    expect(localStorage.getItem("bgpt_impersonating")).toBeNull();
    expect(isImpersonating()).toBe(false);
  });

  it("logout on an ordinary session leaves no impersonation keys behind", () => {
    localStorage.setItem("bgpt_token", TOKEN);
    logout();
    expect(getToken()).toBeNull();
    expect(isImpersonating()).toBe(false);
    expect(Object.keys(localStorage)).toHaveLength(0);
  });
});

describe("postStream error handling", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });
  afterEach(() => {
    localStorage.clear();
  });

  it("fires the global unauthorized handler on 401", async () => {
    localStorage.setItem("bgpt_token", "expired");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        { detail: { code: "token_expired", message: "expired" } },
        401,
      ),
    );
    await expect(
      postStream("/tutor/x/messages/stream", {}, () => {}),
    ).rejects.toMatchObject({
      status: 401,
    });
    // The handler in AuthContext calls logout(); whatever it does, the
    // session token must not survive an expired-session response.
    expect(getToken()).toBe("expired");
    localStorage.setItem("bgpt_token", "expired2");
  });

  it("preserves the server's machine code instead of flattening it", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        { detail: { code: "image_invalid", message: "too large" } },
        422,
      ),
    );
    await expect(
      postStream("/tutor/x/messages/stream", {}, () => {}),
    ).rejects.toMatchObject({
      status: 422,
      code: "image_invalid",
      message: "too large",
    });
  });

  it("reports a rate limit as 429 rather than a generic outage", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        { detail: { code: "rate_limited", message: "slow down" } },
        429,
      ),
    );
    await expect(
      postStream("/tutor/x/messages/stream", {}, () => {}),
    ).rejects.toMatchObject({
      status: 429,
      code: "rate_limited",
    });
  });

  it("rejects when the stream ends without a terminal done frame", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'event: token\ndata: {"text":"অ"}\n\n',
        'event: token\ndata: {"text":"ব"}\n\n',
      ]),
    );
    const seen: string[] = [];
    // Truncated mid-answer (proxy timeout / dropped connection). This used to
    // resolve `null`, and the caller read `message_id` off it -> TypeError.
    await expect(
      postStream("/tutor/x/messages/stream", {}, (t) => seen.push(t)),
    ).rejects.toMatchObject({ code: "llm_unavailable" });
    // Tokens received before the cut are still delivered.
    expect(seen).toEqual(["অ", "ব"]);
  });

  it("parses token + done frames and returns the done payload", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'event: token\ndata: {"text":"অ"}\n\n',
        'event: token\ndata: {"text":"খ"}\n\n',
        'event: done\ndata: {"message_id":42,"grounded":true,"sources":[]}\n\n',
      ]),
    );
    const seen: string[] = [];
    const done = await postStream<{ message_id: number }>(
      "/tutor/x/messages/stream",
      {},
      (t) => seen.push(t),
    );
    expect(seen).toEqual(["অ", "খ"]);
    expect(done.message_id).toBe(42);
  });

  it("does not let a data line after done inherit the done event", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'event: done\ndata: {"message_id":1}\n\n',
        // A stray frame with no event: line of its own. Under the old
        // line-at-a-time parser it was still typed as "done" and overwrote
        // the payload.
        'data: {"message_id":999}\n\n',
      ]),
    );
    const done = await postStream<{ message_id: number }>(
      "/tutor/x/messages/stream",
      {},
      () => {},
    );
    expect(done.message_id).toBe(1);
  });

  it("reassembles a data payload split across two data: lines", async () => {
    // Proxied responses may wrap long lines; the old parser JSON.parsed each
    // line separately and swallowed the failure, losing the frame silently.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(['event: done\ndata: {"message_id":\ndata: 77}\n\n']),
    );
    const done = await postStream<{ message_id: number }>(
      "/tutor/x/messages/stream",
      {},
      () => {},
    );
    expect(done.message_id).toBe(77);
  });

  it("surfaces a server error frame as a failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(['event: error\ndata: {"code":"llm_unavailable"}\n\n']),
    );
    await expect(
      postStream("/tutor/x/messages/stream", {}, () => {}),
    ).rejects.toMatchObject({ code: "llm_unavailable" });
  });
});
