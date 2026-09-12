import { describe, expect, it, vi } from "vitest";
import {
  canInstall,
  initInstallPrompt,
  installed,
  promptInstall,
} from "../lib/installPrompt";

// Single init for the whole file: listeners accumulate if called per test.
initInstallPrompt();

type Promptable = Event & {
  prompt: ReturnType<typeof vi.fn>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

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
  it("is not installable before the browser fires the event", () => {
    expect(canInstall()).toBe(false);
    expect(installed()).toBe(false);
  });

  it("defers the event and exposes the install affordance", () => {
    const evt = fireBeforeInstall("dismissed");
    // preventDefault() is what "deferred" means; the event reports defaultPrevented
    expect(evt.defaultPrevented).toBe(true);
    expect(canInstall()).toBe(true);
  });

  it("promptInstall resolves the user choice and clears the deferred event", async () => {
    const evt = fireBeforeInstall("accepted");
    expect(await promptInstall()).toBe("accepted");
    expect(evt.prompt).toHaveBeenCalledTimes(1);
    expect(canInstall()).toBe(false);
  });

  it("promptInstall is a no-op when nothing is deferred", async () => {
    expect(await promptInstall()).toBe("unavailable");
  });

  it("appinstalled marks the app as installed", () => {
    window.dispatchEvent(new Event("appinstalled"));
    expect(installed()).toBe(true);
    expect(canInstall()).toBe(false);
  });
});
