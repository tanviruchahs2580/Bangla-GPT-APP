/**
 * FE-FIX-018: the modal re-ran its focus effect on every parent render.
 *
 * The effect depended on `[open, onClose]`, and the only production caller
 * passes an inline arrow — a fresh identity on every parent render — so any
 * re-render while the dialog was open reset the scroll lock, re-registered the
 * key handler, ran the restore-focus cleanup and then STOLE FOCUS BACK into the
 * dialog. For a dialog whose content grows (the tutor's evidence modal), that
 * is focus moving under the user mid-read. The effect now depends on `open`
 * alone and reads the callback through a ref.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "../components/ui";
import { t } from "../i18n";

/** The production shape: parent state that re-renders the dialog, and an
    inline `onClose` — the fresh function identity that used to re-run the
    effect and take focus back. */
function Harness() {
  const [n, setN] = useState(0);
  const [open, setOpen] = useState(true);
  return (
    <div>
      <button type="button" data-testid="outside">
        outside
      </button>
      <button type="button" data-testid="rerender" onClick={() => setN(n + 1)}>
        re-render {n}
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title="Evidence">
        <button type="button" data-testid="inside">
          inside
        </button>
      </Modal>
      <span data-testid="counter">{n}</span>
    </div>
  );
}

describe("modal focus stability", () => {
  it("does not steal focus back when the parent re-renders", () => {
    render(<Harness />);
    // Opening focuses into the dialog (its first focusable control is the
    // close button in the header; the wrapper's own children follow).
    const close = screen.getByRole("button", { name: t("close") });
    expect(document.activeElement).toBe(close);

    // The user moves focus elsewhere — a control in the dialog, or anything a
    // browser/AT placed focus on — and then the page re-renders for an
    // unrelated reason (the inline `onClose` identity changes with it).
    screen.getByTestId("inside").focus();
    expect(document.activeElement).toBe(screen.getByTestId("inside"));

    fireEvent.click(screen.getByTestId("rerender"));

    expect(screen.getByTestId("counter").textContent).toBe("1");
    // Pre-fix the effect re-ran on the new `onClose` identity and pulled focus
    // back to the dialog's first control.
    expect(document.activeElement).toBe(screen.getByTestId("inside"));
  });

  it("still focuses into the dialog when it opens, and restores on close", () => {
    function Toggle() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" data-testid="opener" onClick={() => setOpen(true)}>
            open
          </button>
          <Modal open={open} onClose={() => setOpen(false)} title="Evidence">
            <button type="button" data-testid="inside">
              inside
            </button>
          </Modal>
        </>
      );
    }
    render(<Toggle />);
    const opener = screen.getByTestId("opener");
    opener.focus();
    fireEvent.click(opener);
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: t("close") }),
    );

    // Escape still closes through the current handler (the ref indirection),
    // and focus returns to the trigger.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("inside")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("closes through the close button without a stale handler", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Evidence">
        <button type="button">inside</button>
      </Modal>,
    );
    fireEvent.click(screen.getByRole("button", { name: t("close") }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
