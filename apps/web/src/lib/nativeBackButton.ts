import { Capacitor } from "@capacitor/core";

// E6 (2026-11-17 elevation backlog, mobile audit P1-4): the Android hardware
// back button had NO handling — on the root screen it exited the app, and
// mid-quiz attempts / in-flight tutor answers were lost with no confirmation.
// @capacitor/app is native-only: in the browser/PWA its listener never fires,
// so this module is inert on every non-Android surface by construction.
//
// Pages that hold resumable state declare it through markDirty(); the shell
// confirms before a back press may leave. Exit semantics stay with the
// platform: when nothing is dirty, the default handler runs (App.exitApp on
// Android, nothing elsewhere).

type Unsubscribe = () => void;

const dirty = new Set<string>();

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

/** Registers the hardware back handler. Returns a cleanup for HMR/unmount.
 *  No-op outside a native platform (browser, PWA, tests). */
export async function registerBackButton(
  onConfirmLeave: () => void,
): Promise<Unsubscribe> {
  if (!Capacitor.isNativePlatform()) return () => {};
  const { App } = await import("@capacitor/app");
  let confirming = false;
  const handle = App.addListener("backButton", () => {
    if (dirty.size > 0) {
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
    void App.exitApp();
  });
  return () => void handle.then((h) => h.remove());
}
