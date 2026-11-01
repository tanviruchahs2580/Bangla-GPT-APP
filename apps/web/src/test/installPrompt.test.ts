/**
 * PWA install prompt: the module owns process-wide state (a deferred event, an
 * installed flag and a one-time listener registration), so a shared import made
 * the tests order-dependent — under `--sequence.shuffle` a test could inherit
 * another test's "installed" flag or leave a deferred event behind (observed
 * 2026-10-29: 2 failures in 3 shuffled runs). Each test now imports a fresh
 * module and initialises it, so no state crosses a test boundary.
 */
import { describe, expect, it, vi } from "vitest";

type Promptable = Event & {
  prompt: ReturnType<typeof vi.fn>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

async function freshInstall() {
  vi.resetModules();
  const mod = await import("../lib/installPrompt");
  mod.initInstallPrompt();
  return mod;
}

function fireBeforeInstall(
  outcome: "accepted" | "dismissed" = "accepted",
): Promptable {
  const evt = new Event("beforeinstallprompt", {
    cancelable: true,
  }) as Promptable;
  evt.prompt = vi.fn(async () => {});
  evt.userChoice = Promise.resolve({ outcome });
  window.dispatchEvent(evt);
  return evt;
}

describe("installPrompt", () => {
  it("is not installable before the browser fires the event", async () => {
    const { canInstall, installed } = await freshInstall();
    expect(canInstall()).toBe(false);
    expect(installed()).toBe(false);
  });

  it("defers the event and exposes the install affordance", async () => {
    const { canInstall } = await freshInstall();
    const evt = fireBeforeInstall("dismissed");
    // preventDefault() is what "deferred" means; the event reports defaultPrevented
    expect(evt.defaultPrevented).toBe(true);
    expect(canInstall()).toBe(true);
  });

  it("promptInstall resolves the user choice and clears the deferred event", async () => {
    const { canInstall, promptInstall } = await freshInstall();
    const evt = fireBeforeInstall("accepted");
    expect(await promptInstall()).toBe("accepted");
    expect(evt.prompt).toHaveBeenCalledTimes(1);
    expect(canInstall()).toBe(false);
  });

  it("promptInstall is a no-op when nothing is deferred", async () => {
    const { promptInstall } = await freshInstall();
    expect(await promptInstall()).toBe("unavailable");
  });

  it("appinstalled marks the app as installed", async () => {
    const { canInstall, installed } = await freshInstall();
    window.dispatchEvent(new Event("appinstalled"));
    expect(installed()).toBe(true);
    expect(canInstall()).toBe(false);
  });
});
