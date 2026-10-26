import { downloadBlob } from "./lib/download";
import { asText } from "./lib/text";
import { LAST_RESULT_KEY } from "./lib/quizExplain";
import { clearOfflineChapters } from "./lib/offlineStore";

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

/** Absolute API base for direct navigation links (downloads etc.). */
export const apiBase = API_BASE;

export class ApiError extends Error {
  status: number;
  code?: string;
  rawDetail: unknown;
  constructor(
    status: number,
    message: string,
    code?: string,
    rawDetail?: unknown,
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.rawDetail = rawDetail;
  }
}

export interface MeResponse {
  user_id: number;
  email: string;
  role: "student" | "teacher" | "parent" | "admin" | "school_admin";
  profile_id: number | null;
  name: string | null;
  class_level: number | null;
}

const TOKEN_KEY = "bgpt_token";
const ADMIN_TOKEN_KEY = "bgpt_admin_token_backup";
const IMP_ACTIVE_KEY = "bgpt_impersonating";

/** Called when any API call comes back 401 — lets the app force re-login. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

// Auth endpoints where a 401 is part of the API contract (bad credentials / bad code).
// Failing there must surface the inline friendly error, not force a page reload.
const AUTH_401_PATHS = [
  "/auth/login",
  "/auth/verify-email",
  "/auth/reset",
  "/auth/mfa/challenge",
  "/auth/resend-verification",
];

/**
 * Request timeouts (F-015/F-030). A proxy that accepts the connection and
 * then never answers used to hang the UI forever: a stalled GET left a
 * spinner running, and a stalled answer stream left the tutor in its
 * `streaming` state until the student pressed Stop. The stream is NOT
 * bounded as a whole — long generations are legitimate — it gets a
 * connect/first-byte deadline plus a stall deadline that resets on every
 * received chunk.
 */
export const REQUEST_TIMEOUT_MS = 20_000;
export const STREAM_CONNECT_TIMEOUT_MS = 20_000;
export const STREAM_STALL_TIMEOUT_MS = 45_000;

/** Machine-coded timeout error so `friendlyError` and tests can name it. */
function timeoutError(): ApiError {
  return new ApiError(0, "request timed out", "timeout", {
    code: "timeout",
    message: "request timed out",
  });
}

function isAbortError(e: unknown): boolean {
  return (e as { name?: string } | null)?.name === "AbortError";
}

/**
 * First abort wins. `AbortSignal.any` where the runtime has it; a manual
 * controller elsewhere (older WebViews, jsdom) so Stop still works there.
 */
function combineSignals(
  signals: Array<AbortSignal | undefined>,
): AbortSignal | undefined {
  const list = signals.filter((s): s is AbortSignal => s !== undefined);
  if (list.length === 0) return undefined;
  if (list.length === 1) return list[0];
  const anySignal = (
    AbortSignal as unknown as {
      any?: (s: AbortSignal[]) => AbortSignal;
    }
  ).any;
  if (typeof anySignal === "function") return anySignal.call(AbortSignal, list);
  const controller = new AbortController();
  for (const s of list) {
    if (s.aborted) {
      controller.abort();
      break;
    }
    s.addEventListener("abort", () => controller.abort(), { once: true });
  }
  return controller.signal;
}

/**
 * Hard per-request deadline. Implemented with `setTimeout` rather than
 * `AbortSignal.timeout` so tests can drive it with fake timers.
 */
function timeoutGuard(
  ms: number,
  caller?: AbortSignal,
): {
  signal: AbortSignal | undefined;
  timedOut: () => boolean;
  clear: () => void;
} {
  const controller = new AbortController();
  let timedOut = false;
  const id = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, ms);
  return {
    signal: combineSignals([caller, controller.signal]),
    timedOut: () => timedOut,
    clear: () => clearTimeout(id),
  };
}

/** True inside the Capacitor WebView (capacitor://localhost origin). */
function isNativeCapacitor(): boolean {
  try {
    const w = window as unknown as {
      Capacitor?: { isNativePlatform?: () => boolean };
    };
    if (w.Capacitor?.isNativePlatform?.() === true) return true;
    if (window.location?.protocol === "capacitor:") return true;
  } catch {
    /* non-browser (tests/SSR): never native */
  }
  return false;
}

/**
 * The WebView origin (capacitor://localhost) has no same-origin `/api`
 * to talk to — a relative VITE_API_BASE can never work there. Fail with
 * a dedicated machine code (instead of an opaque "network error") so the
 * UI can tell the user the APK was built without a server address.
 * Release builds MUST set VITE_API_BASE to the absolute API URL, e.g.
 * VITE_API_BASE=https://api.example.com/api (see docs/mobile_release.md).
 */
function assertApiBaseUsable(): void {
  if (isNativeCapacitor() && API_BASE.startsWith("/")) {
    throw new ApiError(
      0,
      "native API base unconfigured",
      "api_base_unconfigured",
    );
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

function parseDetail(body: unknown): { message: string; code?: string } {
  if (body && typeof body === "object") {
    const rec = body as Record<string, unknown>;
    if ("detail" in rec) {
      const detail = rec.detail;
      if (detail && typeof detail === "object") {
        const d = detail as Record<string, unknown>;
        return {
          message: asText(d.message) || asText(d),
          code: d.code ? asText(d.code) : undefined,
        };
      }
      return { message: asText(detail) };
    }
    // The Vercel /api proxy (src/lib/apiProxy.ts) answers with a FLAT
    // { code, message } envelope, not FastAPI's { detail }. Reading only
    // `detail` silently dropped that machine code, so a dead API origin fell
    // through to the generic 502 -> bad_gateway fallback and the UI told the
    // user the server was "busy — try again shortly" for an outage that will
    // not resolve on its own. Surface the envelope's own code and message.
    if ("code" in rec || "message" in rec) {
      return {
        message: asText(rec.message) || "Request failed",
        code: rec.code ? asText(rec.code) : undefined,
      };
    }
  }
  if (typeof body === "string" && body) return { message: body };
  return { message: "Request failed" };
}

async function parseSse(
  response: Response,
  onToken: (text: string) => void,
  onChunk?: () => void,
): Promise<Record<string, unknown> | null> {
  const reader = response.body?.getReader();
  if (!reader) return null;
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "";
  let dataLines: string[] = [];
  let done: Record<string, unknown> | null = null;

  // A frame ends at a blank line, and it is the blank line that clears the
  // event name. Parsing line-by-line let a stray `data:` line after a `done`
  // frame inherit that event and overwrite the payload (BUG-005).
  const dispatch = () => {
    if (event && dataLines.length) {
      try {
        // JSON.parse returns `any`; narrow to a record before reading it.
        const data = JSON.parse(dataLines.join("\n")) as Record<
          string,
          unknown
        >;
        if (event === "token") onToken(asText(data.text ?? ""));
        else if (event === "done") done = data;
        else if (event === "error") done = { __error: true, ...data };
      } catch {
        /* ignore malformed frames */
      }
    }
    event = "";
    dataLines = [];
  };

  const consume = (lines: string[]) => {
    for (const raw of lines) {
      const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
      if (line === "") dispatch();
      else if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:"))
        // Multiple `data:` lines belong to one payload; a proxy may wrap a long
        // frame across them.
        dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  };

  for (;;) {
    const { value, done: finished } = await reader.read();
    if (finished) break;
    // Any bytes prove the stream is alive — reset the stall deadline (F-015).
    onChunk?.();
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    consume(lines);
  }
  // Flush whatever the stream left without a trailing blank line.
  buffer += decoder.decode();
  consume(buffer.split("\n"));
  dispatch();
  return done;
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
  opts?: {
    skipUnauthorized?: boolean;
    signal?: AbortSignal;
    /** Per-call timeout override. The bulk roster import hashes up to 200
     * Argon2id passwords server-side (measured >20s — past the default
     * guard), so it is the one documented long call. */
    timeoutMs?: number;
  },
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  // F-015: every non-streaming request is bounded. A caller signal (the
  // tutor's Stop) is combined so either can end the request.
  const caller = opts?.signal ?? options.signal ?? undefined;
  const guard = timeoutGuard(opts?.timeoutMs ?? REQUEST_TIMEOUT_MS, caller);
  try {
    let res: Response;
    try {
      assertApiBaseUsable();
      res = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers,
        signal: guard.signal,
      });
    } catch (e) {
      // The native-misconfiguration guard above throws an ApiError already —
      // let its machine code through instead of masking it as "network".
      if (e instanceof ApiError) throw e;
      if (isAbortError(e)) {
        // A caller-initiated abort must stay an AbortError: callers use it
        // to tell "the user pressed Stop" from a real failure.
        if (caller?.aborted) throw e;
        if (guard.timedOut()) throw timeoutError();
      }
      throw new ApiError(0, "network error", "network");
    }
    if (res.status === 204) return undefined as T;
    if (!res.ok) {
      let parsed: { message: string; code?: string } = {
        message: res.statusText,
      };
      let jsonParseFailed = false;
      try {
        parsed = parseDetail(await res.json());
      } catch {
        jsonParseFailed = true;
      }
      // A stalled error body is still a stalled request.
      if (guard.timedOut()) throw timeoutError();
      if (!parsed.code) {
        // Upstream HTML error pages (dead Cloudflare tunnel 502, proxy 503)
        // carry no machine code — attach one so the UI shows a retry hint
        // instead of the generic fallback.
        if (res.status === 502)
          parsed = { message: parsed.message, code: "bad_gateway" };
        else if (res.status === 503)
          parsed = { message: parsed.message, code: "service_unavailable" };
        else if (jsonParseFailed && res.status === 0)
          parsed = { message: parsed.message, code: "network" };
      }
      if (
        res.status === 401 &&
        !opts?.skipUnauthorized &&
        !AUTH_401_PATHS.some((p) => path.startsWith(p))
      )
        onUnauthorized?.();
      throw new ApiError(res.status, parsed.message, parsed.code, parsed);
    }
    try {
      return (await res.json()) as T;
    } catch (e) {
      if (guard.timedOut() || (isAbortError(e) && !caller?.aborted))
        throw timeoutError();
      throw e;
    }
  } finally {
    guard.clear();
  }
}

export const get = <T>(path: string) => api<T>(path);
export const post = <T>(
  path: string,
  body?: unknown,
  opts?: {
    skipUnauthorized?: boolean;
    signal?: AbortSignal;
    timeoutMs?: number;
  },
) =>
  api<T>(
    path,
    {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    },
    opts,
  );
export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const del = (path: string, body?: unknown) =>
  api<void>(path, {
    method: "DELETE",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

/**
 * POST an SSE endpoint and stream `token` events through `onToken`.
 * Resolves with the parsed `done` event payload.
 *
 * F-015: the connection has a first-byte deadline and each chunk resets a
 * stall deadline, so a proxy that accepts the socket and goes silent ends
 * the turn with a timeout error instead of leaving the UI streaming forever.
 * There is deliberately no whole-stream deadline — a long generation is a
 * legitimate answer.
 */
export async function postStream<T>(
  path: string,
  body: unknown,
  onToken: (text: string) => void,
  options?: { signal?: AbortSignal },
): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  assertApiBaseUsable();

  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let timedOut = false;
  let rejectGate: (e: unknown) => void = () => {};
  // Rejects when either deadline fires, even while the body read is parked
  // on a socket that never sends another byte.
  const gate = new Promise<never>((_, reject) => {
    rejectGate = reject;
  });
  const arm = (ms: number) => {
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => {
      timedOut = true;
      const err = timeoutError();
      rejectGate(err);
      // Tear the real request down too; the race below reports the timeout.
      controller.abort(err);
    }, ms);
  };
  const clearTimer = () => {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
  };

  const run = async (): Promise<T> => {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: combineSignals([options?.signal, controller.signal]),
    });
    if (!res.ok) {
      // postStream bypassed `api()`, so it reported every failure as a generic
      // outage: a 429 rate limit read as "AI unavailable", and an expired session
      // never reached the unauthorized handler (BUG-004).
      let parsed: { message: string; code?: string } = {
        message: res.statusText,
      };
      try {
        parsed = parseDetail(await res.json());
      } catch {
        /* upstream HTML error page: fall back to the status text */
      }
      if (timedOut) throw timeoutError();
      if (res.status === 401 && !AUTH_401_PATHS.some((p) => path.startsWith(p)))
        onUnauthorized?.();
      throw new ApiError(res.status, parsed.message, parsed.code, parsed);
    }
    if (!res.headers.get("content-type")?.includes("text/event-stream"))
      throw new ApiError(res.status, "stream unavailable", "llm_unavailable");
    // Still inside the first-byte window until the first chunk arrives; each
    // chunk then resets the (shorter-windowed) inter-chunk stall deadline.
    const done = await parseSse(res, onToken, () =>
      arm(STREAM_STALL_TIMEOUT_MS),
    );
    if (done && "__error" in done)
      throw new ApiError(502, "stream failed", "llm_unavailable");
    if (!done) {
      // No terminal frame: a proxy timeout, or the server died mid-answer.
      // Resolving null handed callers an object they dereference, so a truncated
      // answer looked like a successful empty one (BUG-005).
      throw new ApiError(
        502,
        "stream ended before completion",
        "llm_unavailable",
      );
    }
    return done as T;
  };

  arm(STREAM_CONNECT_TIMEOUT_MS);
  try {
    return await Promise.race([run(), gate]);
  } finally {
    clearTimer();
  }
}

export interface TokenResponse {
  access_token: string;
  token_type?: string;
  must_change_password?: boolean;
}

export interface LoginResult {
  me: MeResponse;
  mustChangePassword: boolean;
}

export async function login(
  email: string,
  password: string,
): Promise<LoginResult> {
  const res = await post<TokenResponse>("/auth/login", { email, password });
  // MFA-enabled accounts get HTTP 202 + token_type "mfa" (a 5-minute
  // purpose-bound step-up token rejected by every normal route). It must
  // NEVER be stored as a session: the old code saved it, then fetchMe()
  // 401'd and wiped it, surfacing a confusing "verify_failed" instead of
  // the OTP step — MFA users could never sign in.
  if (res.token_type === "mfa") {
    throw new ApiError(202, "two-step verification required", "mfa_required", {
      mfa_token: res.access_token,
    });
  }
  localStorage.setItem(TOKEN_KEY, res.access_token);
  // Validate the session and refresh the authoritative profile from the
  // server. A null here (transient failure AFTER a successful login) must
  // NOT look like a success: the caller would navigate into authed routes
  // with a dead session and bounce straight back out ("instant logout").
  // The verified profile is returned so callers can seed auth state
  // directly — re-fetching /users/me after login doubled the post-login
  // latency (one extra tunnel round-trip per login).
  const probe = await fetchMe();
  if (probe.status === "unreachable") {
    // The token was just issued; the profile call is what failed, and it is
    // a connectivity problem, not an authentication one (F-107).
    throw new ApiError(0, "session verification failed", "verify_unreachable");
  }
  if (probe.status !== "ok") {
    throw new ApiError(0, "session verification failed", "verify_failed");
  }
  return {
    me: probe.me,
    mustChangePassword: res.must_change_password === true,
  };
}

export async function register(input: {
  email: string;
  password: string;
  name: string;
  role: "student" | "teacher" | "parent";
  class_level?: number;
  guardian_consent?: boolean;
}): Promise<void> {
  await post("/auth/register", input);
}

export async function forgotPassword(email: string): Promise<void> {
  await post("/auth/forgot", { email });
}

export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<void> {
  const res = await post<TokenResponse>("/auth/reset", {
    token,
    new_password: newPassword,
  });
  localStorage.setItem(TOKEN_KEY, res.access_token);
}

export async function verifyEmail(token: string): Promise<void> {
  // V1 contract: token only — the endpoint takes no password fields.
  const res = await post<TokenResponse>("/auth/verify-email", { token });
  localStorage.setItem(TOKEN_KEY, res.access_token);
}

export async function resendVerification(email?: string): Promise<void> {
  // Unauthenticated resend (the login stuck-at-email_unverified case):
  // the server accepts an optional email body and always answers 202.
  await post("/auth/resend-verification", email ? { email } : {});
}

/** Complete the MFA step-up: exchange the 202 mfa_token + OTP code for a real session. */
export async function mfaChallenge(
  mfaToken: string,
  code: string,
): Promise<LoginResult> {
  const res = await post<TokenResponse>("/auth/mfa/challenge", {
    mfa_token: mfaToken,
    code,
  });
  localStorage.setItem(TOKEN_KEY, res.access_token);
  const probe = await fetchMe();
  if (probe.status === "unreachable") {
    // The token was just issued; the profile call is what failed, and it is
    // a connectivity problem, not an authentication one (F-107).
    throw new ApiError(0, "session verification failed", "verify_unreachable");
  }
  if (probe.status !== "ok") {
    throw new ApiError(0, "session verification failed", "verify_failed");
  }
  return {
    me: probe.me,
    mustChangePassword: res.must_change_password === true,
  };
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const res = await post<TokenResponse>("/auth/change-password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
  localStorage.setItem(TOKEN_KEY, res.access_token);
}

/** Student generates a single-use code (BGPT-XXXXXXXXXXXXXXXX) a parent can redeem to link. */
export async function generateInviteCode(): Promise<{
  code: string;
  expires_in_minutes: number;
}> {
  return post("/students/me/invite-code");
}

/**
 * Outcome of the session probe.
 *
 * F-107: this used to return `MeResponse | null`, collapsing three different
 * situations into one. The worst is "the API could not be reached at all",
 * which is what a total outage looks like: `fetchMe` returned null, the
 * provider treated the user as signed out, and every authenticated route
 * redirected to /login with no banner, no offline notice and no explanation.
 * A child whose session cannot be verified because the server is down was
 * given the same dead end as a child whose password was wrong.
 *
 * `unreachable` is kept distinct so the UI can say so and offer a retry,
 * and so the stored token is NOT wiped by an outage.
 */
export type SessionProbe =
  | { status: "ok"; me: MeResponse }
  | { status: "unauthenticated" }
  | { status: "unreachable" };

export async function fetchMe(): Promise<SessionProbe> {
  if (!getToken()) {
    return { status: "unauthenticated" };
  }
  try {
    return { status: "ok", me: await get<MeResponse>("/users/me") };
  } catch (e) {
    // Only a 401 proves the token is dead. Transient failures (network
    // blips, tunnel reconnects, non-JSON error pages) must NOT wipe a
    // freshly stored token — that turned every hiccup into an "instant
    // logout" right after login.
    if (e instanceof ApiError && e.status === 401) {
      await logout();
      return { status: "unauthenticated" };
    }
    // 403 is a real answer ("your session is no longer permitted"), not an
    // outage, so it ends the session. Anything else — a network error, a 5xx,
    // a 502 from the proxy, a non-JSON body — means we do not know.
    if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
      await logout();
      return { status: "unauthenticated" };
    }
    return { status: "unreachable" };
  }
}

/**
 * Every localStorage key that carries data belonging to the signed-in user.
 * `bgpt_lang` (language) and `bgpt_theme` are deliberately absent: they are
 * device preferences, not user data, and must survive a sign-out (F-036).
 */
const USER_STORAGE_KEYS = [
  TOKEN_KEY,
  ADMIN_TOKEN_KEY,
  IMP_ACTIVE_KEY,
  "lastChapter",
  // fontScale is deliberately NOT here: it is a device accessibility
  // preference by the same argument that keeps bgpt_theme and bgpt_lang —
  // a low-vision user on a shared device must not lose their text size on
  // every sign-out.
  "bgpt-lowdata",
  "bgpt_teacher_default_class",
];

/** Extra teardown the app registers for logout — the react-query cache. */
let logoutCleanup: (() => void) | null = null;
export function setLogoutCleanup(fn: (() => void) | null): void {
  logoutCleanup = fn;
}

/**
 * Clear every trace of the signed-in user from this device (F-036).
 *
 * Awaitable on purpose: the offline chapter store (IndexedDB) and the
 * registered teardown hooks must finish before sign-out navigates away, or
 * the next user on a shared device inherits this one's downloaded chapters,
 * last-open chapter and full last quiz result.
 */
export async function logout(): Promise<void> {
  // S-011: revoke the session server-side first. A token left valid in a
  // proxy log or on a shared device used to live out its full 60 minutes;
  // POST /auth/logout parks its jti in the fail-closed revocation store.
  // Best-effort on purpose: local sign-out must succeed even offline.
  try {
    await post<void>("/auth/logout", {});
  } catch {
    /* offline or token already gone — local wipe still happens below */
  }
  for (const key of USER_STORAGE_KEYS) localStorage.removeItem(key);
  sessionStorage.removeItem(LAST_RESULT_KEY);
  logoutCleanup?.();
  try {
    await clearOfflineChapters();
  } catch {
    /* the in-memory fallback is already gone; IDB clearing is best-effort */
  }
}

/**
 * Sign out EVERYWHERE (S-011): stamps the server-side token epoch, so every
 * outstanding session of the account fails its next request. Returns once
 * confirmed — callers then complete a local logout.
 */
export const revokeAllSessions = () =>
  post<void>("/users/me/sessions/revoke", {});

/* -------- Learn catalog (grounded corpus) -------- */
export const getSubjects = (classLevel?: number) =>
  get<import("./types").SubjectOut[]>(
    `/learn/subjects${classLevel ? `?class_level=${classLevel}` : ""}`,
  );

export const getSubjectChapters = (subject: string, classLevel?: number) =>
  get<import("./types").ChapterSummaryOut[]>(
    `/learn/subjects/${encodeURIComponent(subject)}/chapters${
      classLevel ? `?class_level=${classLevel}` : ""
    }`,
  );

export const getChapterContent = (
  subject: string,
  chapter: string,
  classLevel?: number,
) =>
  get<import("./types").ChapterContentOut>(
    `/learn/subjects/${encodeURIComponent(subject)}/chapters/${encodeURIComponent(
      chapter,
    )}${classLevel ? `?class_level=${classLevel}` : ""}`,
  );

export const getLearnProgress = (subject?: string, classLevel?: number) => {
  const qs = new URLSearchParams();
  if (subject) qs.set("subject", subject);
  if (classLevel) qs.set("class_level", String(classLevel));
  const q = qs.toString() ? `?${qs}` : "";
  return get<import("./types").ChapterProgressOut[]>(`/learn/progress${q}`);
};

export const upsertLearnProgress = (payload: {
  subject: string;
  chapter: string;
  class_level: number;
  read_pct?: number;
  completed?: boolean;
  bookmarked?: boolean;
}) => post<import("./types").ChapterProgressOut>("/learn/progress", payload);

/* -------- support ops -------- */

export interface ImpersonateOut {
  access_token: string;
  user_id: number;
  role: string;
  expires_in_min: number;
}

/**
 * Admin mints a short-lived support token for a target user. The admin's own
 * token is kept aside so `exitImpersonation` can restore it; every request in
 * between runs as the impersonated user (the server audits start and exit).
 */
export async function startImpersonation(
  userId: number,
  reason: string,
): Promise<ImpersonateOut> {
  const adminToken = getToken();
  const res = await post<ImpersonateOut>(`/admin/users/${userId}/impersonate`, {
    reason,
  });
  if (adminToken) localStorage.setItem(ADMIN_TOKEN_KEY, adminToken);
  localStorage.setItem(IMP_ACTIVE_KEY, String(res.user_id));
  localStorage.setItem(TOKEN_KEY, res.access_token);
  return res;
}

export function isImpersonating(): boolean {
  return localStorage.getItem(IMP_ACTIVE_KEY) !== null;
}

/**
 * Revokes the impersonation token server-side (POST /auth/impersonate/exit)
 * and puts the admin's own token back. The revoke is what makes the exit
 * real; the 15-min token expiry is only the backstop.
 */
export async function exitImpersonation(): Promise<void> {
  try {
    await post<void>("/auth/impersonate/exit");
  } catch {
    /* expired or already-revoked tokens still leave the local state fixable */
  }
  const adminToken = localStorage.getItem(ADMIN_TOKEN_KEY);
  if (adminToken) localStorage.setItem(TOKEN_KEY, adminToken);
  localStorage.removeItem(ADMIN_TOKEN_KEY);
  localStorage.removeItem(IMP_ACTIVE_KEY);
}

export const getFeedbackQueue = (
  status: "open" | "all",
  limit = 20,
  offset = 0,
) =>
  get<import("./types").FeedbackQueuePage>(
    `/admin/feedback?status=${status}&limit=${limit}&offset=${offset}`,
  );

export const triageFeedback = (
  id: number,
  payload: { triaged: boolean; note?: string },
) =>
  patch<import("./types").FeedbackAdminRow>(`/admin/feedback/${id}`, payload);

export const getStatus = () => get<import("./types").StatusOut>("/status");

/* -------- Blueprint v1: notifications / notes / documents / jobs / workload -------- */

export interface NotificationItem {
  id: number;
  kind: string;
  /** i18n code resolved client-side (server never sends final copy). */
  code: string;
  params: Record<string, string | number>;
  link: string | null;
  read_at: string | null;
  created_at: string | null;
}

export interface NotificationList {
  items: NotificationItem[];
  unread_count: number;
}

export const getNotifications = () => get<NotificationList>("/notifications");
export const markNotificationRead = (id: number) =>
  post<NotificationItem>(`/notifications/${id}/read`);

export interface SavedNote {
  id: number;
  title: string;
  body: string;
  source: string;
  source_ref: Record<string, unknown> | null;
  created_at: string | null;
}

export const getNotes = (limit = 100) =>
  get<SavedNote[]>(`/notes?limit=${limit}`);
export const createNote = (input: {
  title?: string;
  body: string;
  source?: "tutor" | "chapter" | "other";
  source_ref?: Record<string, unknown>;
}) => post<SavedNote>("/notes", input);
export const deleteNote = (id: number) => del(`/notes/${id}`);

export interface TeacherDocument {
  id: number;
  /**
   * Known values today: worksheet, answer_key, homework, rubric, lesson_plan.
   * Typed as `string` rather than a closed union because the API can add kinds
   * and a client that breaks on an unknown one is worse than one that displays
   * it; the list is kept here as the documentation it was pretending to be.
   */
  kind: string;
  class_level: number;
  subject: string;
  chapter: string | null;
  title: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface GeneratedDocument extends TeacherDocument {
  sources: import("./types").SourceRef[];
}

/**
 * Authed binary GET through the shared client (F-032): same base-URL guard,
 * 401 handling, error envelope and timeout as every JSON call. Raw `fetch`
 * at a call site bypassed all of it (and only worked in the web build).
 */
export async function getBlob(
  path: string,
): Promise<{ blob: Blob; contentType: string }> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  assertApiBaseUsable();
  const guard = timeoutGuard(REQUEST_TIMEOUT_MS);
  try {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}${path}`, {
        headers,
        signal: guard.signal,
      });
    } catch (e) {
      if (e instanceof ApiError) throw e;
      if (guard.timedOut()) throw timeoutError();
      throw new ApiError(0, "network error", "network");
    }
    if (res.status === 401 && !AUTH_401_PATHS.some((p) => path.startsWith(p)))
      onUnauthorized?.();
    if (!res.ok) {
      let parsed: { message: string; code?: string } = {
        message: res.statusText,
      };
      try {
        parsed = parseDetail(await res.json());
      } catch {
        /* upstream HTML error page: fall back to the status text */
      }
      if (guard.timedOut()) throw timeoutError();
      throw new ApiError(res.status, parsed.message, parsed.code, parsed);
    }
    return {
      blob: await res.blob(),
      contentType: res.headers.get("content-type") ?? "",
    };
  } finally {
    guard.clear();
  }
}

/**
 * Authed binary download (auth is header-based, a bare <a href> would 401).
 * The server may fall back to an HTML print view when shaping libs are
 * unavailable — that variant opens in a new tab instead of downloading.
 */
export async function downloadTeacherDocumentPdf(
  doc: TeacherDocument,
): Promise<void> {
  const { blob, contentType } = await getBlob(
    `/teacher/documents/${doc.id}/pdf`,
  );
  downloadBlob(blob, `document-${doc.id}-${doc.kind}.pdf`, {
    openInTab: contentType.includes("html"),
  });
}

export interface AiJob {
  id: string;
  kind: string;
  /** Known values today: queued, generating, validating, ready, failed.
   *  Open string for the same reason as TeacherDocument.kind. */
  status: string;
  payload: Record<string, unknown>;
  result: { document_id?: number } | null;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TeacherWorkload {
  counts: Record<string, number>;
  minutes_saved: Record<string, number>;
  total_minutes_saved: number;
  estimate: boolean;
  methodology: string;
}

export const getTeacherWorkload = () =>
  get<TeacherWorkload>("/teacher/workload");

// --- school section (school_admin = own school; admin = platform) --------

export interface SchoolStudentRow {
  student_id: number;
  name: string;
  class_level: number;
  section: string;
  last_active: string | null;
  quiz_attempts: number;
}
export interface SchoolStudentPage {
  total: number;
  limit: number;
  offset: number;
  items: SchoolStudentRow[];
}
export interface SchoolTeacherRow {
  teacher_id: number;
  name: string;
  subjects: string[];
  classrooms: number;
}
export interface SchoolClassRow {
  classroom_id: number;
  class_level: number;
  section: string;
  students: number;
  quiz_attempts: number;
  attempts_graded: number;
  avg_quiz_accuracy: number | null;
}
export interface SchoolCoverageRow {
  class_level: number;
  content_subjects: string[];
  asked_subjects: string[];
  uncovered_subjects: string[];
  chapters_available: number;
  chapters_read: number;
  chapters_completed: number;
}
export interface SchoolCoverageOut {
  rows: SchoolCoverageRow[];
}
export interface SchoolActiveDay {
  date: string;
  students: number;
}
export interface SchoolAnalytics {
  days: number;
  active_by_date: SchoolActiveDay[];
  daily_active_avg: number;
  questions_asked: number;
  quiz_attempts: number;
  attempts_graded: number;
  avg_quiz_score_pct: number | null;
}

export const getSchoolStudents = (limit = 50, offset = 0) =>
  get<SchoolStudentPage>(`/school/students?limit=${limit}&offset=${offset}`);
export const getSchoolTeachers = () =>
  get<SchoolTeacherRow[]>("/school/teachers");
export const getSchoolClasses = () => get<SchoolClassRow[]>("/school/classes");
export const getSchoolCoverage = () =>
  get<SchoolCoverageOut>("/school/coverage");
export const getSchoolAnalytics = (days = 30) =>
  get<SchoolAnalytics>(`/school/analytics?days=${days}`);

// --- parent period report -------------------------------------------------

export interface ParentReport {
  student_id: number;
  name: string;
  class_level: number;
  period: string;
  window_start: string;
  window_end: string;
  quizzes_taken: number;
  quizzes_graded: number;
  avg_score_pct: number | null;
  chapters_read: number;
  chapters_completed: number;
  questions_asked: number;
  weak_chapters: string[];
  strengths: string[];
  suggestion_code: string;
  suggestion_params: Record<string, unknown>;
}

export const getParentReport = (
  studentId: number,
  period: "weekly" | "monthly" = "weekly",
) =>
  get<ParentReport>(
    `/parents/me/children/${studentId}/report?period=${period}`,
  );

// --- admin AI quality dashboard --------------------------------------------

export interface AdminAiQuality {
  days: number;
  answers_total: number;
  grounded_count: number;
  ungrounded_count: number;
  refusals_total: number;
  refusals_by_reason: Record<string, number>;
  thumbs_up: number;
  thumbs_down: number;
  low_confidence_count: number;
  by_model: Record<string, number>;
}

export const getAdminAiQuality = (days = 30) =>
  get<AdminAiQuality>(`/admin/ai/quality?days=${days}`);

// --- student learning preferences + memory ----------------------------------

export interface StudentPrefs {
  memory_enabled: boolean;
  learning_prefs: Record<string, unknown>;
}
export interface MemoryFacts {
  memory_enabled: boolean;
  facts: Record<string, unknown>;
  on_disable_note_code: string;
}

export const getMyPrefs = () => get<StudentPrefs>("/students/me/prefs");
export const patchMyPrefs = (body: {
  memory_enabled?: boolean;
  learning_prefs?: Record<string, unknown>;
}) => patch<StudentPrefs>("/students/me/prefs", body);
export const getMyMemory = () => get<MemoryFacts>("/students/me/memory");
export const clearMyMemory = () => del("/students/me/memory");
export const getMyReport = (period: "weekly" | "monthly" = "weekly") =>
  get<ParentReport>(`/students/me/report?period=${period}`);
