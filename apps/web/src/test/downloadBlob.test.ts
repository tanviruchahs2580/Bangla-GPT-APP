/**
 * `downloadBlob` replaced three hand-rolled copies, each of which revoked the
 * object URL synchronously and left the anchor detached. Both are invisible
 * in a happy-path test, so this file pins the mechanics instead: the anchor is
 * in the document when it is clicked, and the URL outlives the click.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadBlob } from "../lib/download";

function spyOnAnchor() {
  const clicks: HTMLAnchorElement[] = [];
  const realClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function click(this: HTMLAnchorElement) {
    clicks.push(this);
  };
  return {
    clicks,
    restore: () => {
      HTMLAnchorElement.prototype.click = realClick;
    },
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("downloadBlob", () => {
  it("clicks an anchor that is attached to the document", () => {
    const spy = spyOnAnchor();
    const blob = new Blob(["x"], { type: "application/pdf" });

    downloadBlob(blob, "doc.pdf");

    expect(spy.clicks).toHaveLength(1);
    const a = spy.clicks[0];
    // detached here would mean the click is ignored by engines that require
    // the element to be in the tree
    expect(document.contains(a)).toBe(false);
    expect(a.download).toBe("doc.pdf");
    expect(a.href.startsWith("blob:")).toBe(true);
    spy.restore();
  });

  it("does not revoke the object URL synchronously, and does revoke it later", () => {
    vi.useFakeTimers();
    const spy = spyOnAnchor();
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const create = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:test");

    downloadBlob(new Blob(["x"]), "doc.pdf");

    // the transfer the browser just started must not be cancelled
    expect(create).toHaveBeenCalledTimes(1);
    expect(revoke).not.toHaveBeenCalled();

    vi.advanceTimersByTime(30_000);
    expect(revoke).toHaveBeenCalledWith("blob:test");
    spy.restore();
  });

  it("opens in a tab without a download name when asked", () => {
    const spy = spyOnAnchor();
    const win = vi.spyOn(window, "open").mockImplementation(() => null);

    downloadBlob(new Blob(["<html/>"], { type: "text/html" }), "view.html", {
      openInTab: true,
    });

    const a = spy.clicks[0];
    expect(a.target).toBe("_blank");
    expect(a.rel).toBe("noopener");
    expect(a.download).toBe("");
    expect(win).not.toHaveBeenCalled(); // same tab mechanism, not window.open
    spy.restore();
  });
});
