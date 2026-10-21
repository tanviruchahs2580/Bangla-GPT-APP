/**
 * Request deadlines and the abort plumbing every API call shares (F-015/F-030).
 *
 * Extracted from `api.ts` for cohesion and file size: this is transport
 * policy, not API surface. `api.ts` re-exports every name here, so callers
 * and tests keep importing them from `api`.
 */

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

/**
 * Deadline for the bulk endpoints whose server work is O(rows) by contract.
 *
 * G-19: the classroom CSV import (`POST /teacher/classrooms/{id}/import`) hashes
 * one invite code per row with Argon2id inside the request, so the documented
 * ceiling -- `IMPORT_MAX_ROWS = 200` rows -- costs the server ~10 s on an idle
 * host (measured 9.9 / 10.7 / 10.8 s here; ~50 ms per row) and proportionally
 * more on a loaded one. Against the 20 s default the teacher saw "The server
 * isn't responding" while the API was still enrolling: the accounts were
 * created *after* the client gave up, so the UI reported a failure for a
 * success. The deadline stays bounded, it is simply no longer shorter than
 * the operation the API itself advertises.
 */
export const BULK_REQUEST_TIMEOUT_MS = 120_000;

/** True when an error came from an aborted fetch (caller Stop or deadline). */
export function isAbortError(e: unknown): boolean {
  return (e as { name?: string } | null)?.name === "AbortError";
}

/**
 * First abort wins. `AbortSignal.any` where the runtime has it; a manual
 * controller elsewhere (older WebViews, jsdom) so Stop still works there.
 */
export function combineSignals(
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
export function timeoutGuard(
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
