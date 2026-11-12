/**
 * The install affordance on the anonymous routes.
 *
 * Regression guard for a real defect: `installPrompt.ts` defers
 * `beforeinstallprompt` (calling `preventDefault()` so the app can own the
 * install flow), which also suppresses the browser's own install UI. The app's
 * replacement button lived only in `AppShell`, which wraps only the signed-in
 * routes -- so on `/login` there was no install route at all: the prompt had
 * been deferred and the button did not exist yet. The PWA could only be
 * installed by first creating an account.
 *
 * These tests pin that a visitor can install without being signed in.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PublicInstallButton } from "../components/PublicInstallButton";
import { initInstallPrompt, installed } from "../lib/installPrompt";
import { setLang, t } from "../i18n";

/** Dispatch the event Chromium fires when the app is installable. */
function offerInstall() {
  const evt = new Event("beforeinstallprompt") as Event & {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
  };
  evt.prompt = vi.fn(() => Promise.resolve());
  evt.userChoice = Promise.resolve({ outcome: "accepted" as const });
  window.dispatchEvent(evt);
  return evt;
}

describe("public install affordance", () => {
  beforeEach(() => {
    setLang("bn");
    initInstallPrompt();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("offers install to a signed-out visitor on a public route", async () => {
    // Nothing to offer until the browser says the app is installable.
    expect(installed()).toBe(false);
    const { rerender } = render(<PublicInstallButton />);

    offerInstall();
    rerender(<PublicInstallButton />);

    const button = await screen.findByRole("button", {
      name: t("installApp"),
    });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("type", "button");
  });

  it("calls the deferred prompt when tapped, and hides once chosen", async () => {
    const evt = offerInstall();
    render(<PublicInstallButton />);
    const button = await screen.findByRole("button", {
      name: t("installApp"),
    });

    button.click();
    await Promise.resolve();

    expect(evt.prompt).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when the browser has not offered install", () => {
    render(<PublicInstallButton />);
    expect(
      screen.queryByRole("button", { name: t("installApp") }),
    ).not.toBeInTheDocument();
  });

  it("is reachable without authentication by construction", () => {
    // The component takes no auth context, so it cannot accidentally become
    // conditional on a session the way the AppShell button is.
    expect(PublicInstallButton.length).toBe(0);
  });
});
