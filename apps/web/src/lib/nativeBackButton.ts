import { Capacitor } from "@capacitor/core";

// E6 (2026-11-17 elevation backlog, mobile audit P1-4): the Android hardware
// back button had NO handling — on the root screen it exited the app, and
// mid-quiz attempts / in-flight tutor answers were lost with no confirmation.
// @capacitor/app is native-only: in the browser/PWA its listener never fires,
// so this module is inert on every non-Android surface by construction.
//
// vc206 (2026-11-18) widened the semantics: exitApp-on-clean was wrong on
// every nested route — a back press must first walk the app's OWN route
// stack and only exit at the true root. The priority order below is the
// documented policy; resolveBackAction() is the single testable decision
// point so the order itself is unit-tested without a native bridge.
//
//   1. IME/keyboard — an editable element holds focus: blur it and let the
//      keyboard close, matching the system's own back-first-closes-keyboard
//      behaviour (the WebView delivers the event to us even while the IME
//      is up, because the listener is registered).
//   2. Topmost dismissible overlay — Modal/ConfirmDialog register while
//      open (components/ui.tsx); back dismisses the topmost one.
//   3. Resumable state — a page that declared markDirty() gets the shared
//      confirm dialog (AppShell). Cancel preserves the exact state.
//   4. In-app history — when the shell's route stack has a previous in-app
//      entry, go back through it (history.back()). The stack is fed by
//      AppShell via trackRoute() from React Router's own navigation type,
//      so a deep link / PWA cold start (stack length 1) can never send the
//      user out of the app to a foreign history entry.
//   5. True root, clean, no overlay — exit the app (platform default).

type Unsubscribe = () => void;

const dirty = new Set<string>();

/** Dismissible overlays (modals, the back-confirm dialog), push order =
 *  visual stacking order; the LAST entry is the topmost. */
const overlays: Array<() => void> = [];

/** In-app route stack, fed by AppShell from React Router's navigation type. */
const routeStack: string[] = [];

/** Clears the route stack. AppShell calls this on mount: the stack must
 *  never survive a logout/login cycle (pre-logout routes are stale — going
 *  "back" into them would bounce an unauthenticated user at the login wall). */
export function resetRoutes(): void {
  routeStack.length = 0;
}

/** A page with resumable state (active quiz attempt, streaming answer,
 *  unsent draft) declares itself until it is safe to leave. */
export function markDirty(key: string): Unsubscribe {
  dirty.add(key);
  return () => {
    dirty.delete(key);
  };
}

export function isDirty(): boolean {
  return dirty.size > 0;
}

/** Registers a dismissible overlay (Modal uses this while open). Returns
 *  its unregister fn. Browser/PWA-safe: the registry is only consulted by
 *  the native back listener. */
export function pushOverlay(dismiss: () => void): Unsubscribe {
  overlays.push(dismiss);
  return () => {
    const i = overlays.indexOf(dismiss);
    if (i !== -1) overlays.splice(i, 1);
  };
}

/** Feed the in-app route stack. Called by AppShell on every location change
 *  with React Router's own navigation type, so the stack mirrors what the
 *  router did (PUSH grows it, REPLACE rewrites the top, POP shrinks it). */
export function trackRoute(path: string, type: "PUSH" | "REPLACE" | "POP") {
  if (routeStack.length === 0) {
    // Seed (first track after mount / cold start): the current path is the
    // bottom of this session's stack — there is nothing in-app behind it.
    routeStack.push(path);
    return;
  }
  if (type === "PUSH") {
    if (routeStack[routeStack.length - 1] !== path) routeStack.push(path);
  } else if (type === "REPLACE") {
    routeStack[routeStack.length - 1] = path;
  } else if (routeStack.length > 1 && routeStack[routeStack.length - 1] !== path) {
    // Browser/router back landed on an earlier in-app entry: drop the one
    // it left. (A POP onto the current top — e.g. a re-render — is a no-op.)
    routeStack.pop();
  }
}

/** Test seam + listener input: what should the next back press do? */
export function resolveBackAction(): "keyboard" | "overlay" | "confirm" | "back" | "exit" {
  const el = document.activeElement;
  if (
    el instanceof HTMLElement &&
    (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)
  ) {
    return "keyboard";
  }
  if (overlays.length > 0) return "overlay";
  if (dirty.size > 0) return "confirm";
  if (routeStack.length > 1) return "back";
  return "exit";
}

/** Registers the hardware back handler. Returns a cleanup for HMR/unmount.
 *  No-op outside a native platform (browser, PWA, tests). */
export async function registerBackButton(
  onConfirmLeave: () => void,
): Promise<Unsubscribe> {
  if (!Capacitor.isNativePlatform()) return () => {};
  const { App } = await import("@capacitor/app");
  let confirming = false;
  const handle = App.addListener("backButton", () => {
    const action = resolveBackAction();
    if (action === "keyboard") {
      (document.activeElement as HTMLElement).blur();
      return;
    }
    if (action === "overlay") {
      overlays[overlays.length - 1]();
      return;
    }
    if (action === "confirm") {
      // One press asks; the dialog is the only way out of a dirty route.
      if (!confirming) {
        confirming = true;
        onConfirmLeave();
        // Re-arm after the dialog closes either way (it self-closes).
        window.setTimeout(() => {
          confirming = false;
        }, 1200);
      }
      return;
    }
    if (action === "back") {
      // Guarded by the route stack: the previous entry is in-app.
      window.history.back();
      return;
    }
    void App.exitApp();
  });
  return () => void handle.then((h) => h.remove());
}
