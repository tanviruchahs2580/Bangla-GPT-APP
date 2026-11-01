/**
 * PWA-02: service-worker update lifecycle.
 *
 * `sw.js` deliberately does not `skipWaiting` on an update over a live
 * session: taking control immediately would serve a new index.html that
 * references hashed chunks the open page never loaded. The user is told the
 * update is ready (the banner subscribes below) and only an explicit accept
 * hands over: the waiting worker gets SKIP_WAITING, and the page reloads once
 * `controllerchange` confirms the new worker controls it.
 */

type Listener = (waiting: boolean) => void;

let registration: ServiceWorkerRegistration | null = null;
let waiting = false;
/** Only an accepted update may reload the page; clients.claim() on a first
 * install also fires controllerchange and must not cause a surprise reload. */
let accepted = false;
const listeners = new Set<Listener>();

function notify(): void {
  listeners.forEach((fn) => fn(waiting));
}

/** Subscribe to the waiting-update state; returns the unsubscribe function. */
export function subscribeUpdate(fn: Listener): () => void {
  listeners.add(fn);
  fn(waiting);
  return () => {
    listeners.delete(fn);
  };
}

export function updateWaiting(): boolean {
  return waiting;
}

/**
 * Register `/sw.js` (production builds only — callers gate on import.meta.env.
 * PROD) and start watching for an update over a live session.
 */
export async function registerServiceWorker(): Promise<void> {
  const reg = await navigator.serviceWorker.register("/sw.js");
  registration = reg;

  const markWaiting = (): void => {
    // No controller yet means a first install: the worker claims the page and
    // there is nothing for the user to accept.
    if (!navigator.serviceWorker.controller) return;
    waiting = true;
    notify();
  };

  if (reg.waiting) markWaiting();

  reg.addEventListener("updatefound", () => {
    const installing = reg.installing;
    if (!installing) return;
    installing.addEventListener("statechange", () => {
      if (installing.state === "installed") markWaiting();
    });
  });

  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (accepted) window.location.reload();
  });
}

/** Accept the waiting update: hand over, then reload onto the new shell. */
export function applyUpdate(): void {
  accepted = true;
  const pending = registration?.waiting;
  if (pending) {
    pending.postMessage({ type: "SKIP_WAITING" });
    return;
  }
  // Nothing waiting (e.g. a stale banner): a plain reload is still the way to
  // pick up whatever the server now serves.
  window.location.reload();
}
