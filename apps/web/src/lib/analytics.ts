import { post } from "../api";

/**
 * Blueprint §34 event-driven analytics: fire-and-forget product events.
 * The API persists only sanitized, PII-free props (server-side filter) — so
 * callers send short scalar metadata here and never message content.
 */
export type EventProps = Record<string, string | number | boolean>;

const inflight = new Map<string, number>();
const DEDUPE_WINDOW_MS = 2000;

export function track(name: string, props?: EventProps): void {
  const now = Date.now();
  const last = inflight.get(name);
  if (last !== undefined && now - last < DEDUPE_WINDOW_MS) return;
  inflight.set(name, now);
  try {
    // skipUnauthorized: analytics is best-effort and also fires while logged
    // out (e.g. welcome CTAs). A 401 here must never trip the global handler
    // that force-redirects to /login — that bounce destroys the register flow.
    void post(
      "/events",
      { name, props: props ?? {} },
      { skipUnauthorized: true },
    ).catch(() => {
      // analytics must never break a user flow
    });
  } catch {
    // ignore: analytics is best-effort
  }
}
