/**
 * The markdown fallback is not a live region.
 *
 * FE-FIX (live-region contract): `SafeMarkdownLazy`'s Suspense fallback wrapped
 * the RAW partial content in `aria-live="polite"`, and the tutor's stream
 * flushes every 80 ms — so a screen reader re-announced a half-rendered answer
 * up to a dozen times per turn. That contradicts the deliberate
 * single-announcement contract the tutor page implements (and that
 * tutorAnnounce.test.tsx asserts). The fallback is static content about to be
 * replaced.
 *
 * The lazy chunk is held open by a gate so the fallback is a deterministic
 * state to assert, rather than a race against the loader.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SafeMarkdownLazy } from "../lib/safeMarkdownLazy";

const gate = vi.hoisted(() => {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release: () => release() };
});

vi.mock("../lib/safeMarkdown", async () => {
  await gate.promise;
  return { SafeMarkdown: () => <div data-testid="rendered">rendered</div> };
});

afterEach(() => {
  gate.release();
});

describe("SafeMarkdownLazy fallback", () => {
  it("renders the partial content without announcing it", async () => {
    const { container } = render(
      <SafeMarkdownLazy content="অর্ধেক উত্তর" className="reader-md" />,
    );

    const fallback = container.querySelector(".reader-md");
    expect(fallback?.textContent).toBe("অর্ধেক উত্তর");
    expect(fallback?.getAttribute("aria-live")).toBeNull();
    expect(fallback?.getAttribute("role")).toBeNull();
    expect(container.querySelector('[aria-live="polite"]')).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();

    // ...and once the renderer arrives it is not a live region either: the
    // single announcement belongs to the tutor page's own announcer.
    gate.release();
    await waitFor(() => expect(screen.getByTestId("rendered")).toBeTruthy());
    expect(container.querySelector('[aria-live="polite"]')).toBeNull();
  });
});
