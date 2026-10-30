/** shared primitives — Modal (focus trap, Esc, backdrop close),
 *  Skeleton, Field, Segmented, Avatar, and the i18n Spinner default. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  Avatar,
  Field,
  Modal,
  Segmented,
  Skeleton,
  Spinner,
} from "../components/ui";
import { setLang, t } from "../i18n";

function ModalHarness({ onClose }: { onClose?: () => void }) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button onClick={() => setOpen(true)}>open</button>
      <button onClick={onClose}>outside-sentinel</button>
      <Modal
        open={open}
        onClose={() => {
          setOpen(false);
          onClose?.();
        }}
        title={t("evidenceTitle")}
      >
        <button>inside-action</button>
        <p>body</p>
      </Modal>
    </>
  );
}

describe("ui primitives", () => {
  it("Modal renders via portal with dialog semantics and closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { container } = render(<ModalHarness onClose={onClose} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    // portal: the backdrop is appended directly to document.body, outside
    // the rendered app tree
    expect(container.querySelector(".modal-backdrop")).toBeNull();
    expect(
      document.body.querySelector(":scope > .modal-backdrop"),
    ).not.toBeNull();
    expect(screen.getByText(t("evidenceTitle"))).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Modal traps Tab focus inside the dialog", async () => {
    const user = userEvent.setup();
    render(<ModalHarness />);
    // focus order inside the dialog: close button → inside-action
    const closeBtn = screen.getByRole("button", { name: t("close") });
    closeBtn.focus();
    await user.tab();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "inside-action" }),
    );
    // Tab from the last focusable wraps back to the first, never outside
    await user.tab();
    expect(document.activeElement).toBe(closeBtn);
  });

  it("Modal closes on backdrop click", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<ModalHarness onClose={onClose} />);
    await user.click(document.querySelector(".modal-backdrop")!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Skeleton maps variants to the design-system classes", () => {
    const { container } = render(
      <>
        <Skeleton variant="card" />
        <Skeleton variant="row" />
        <Skeleton variant="avatar" />
        <Skeleton w="60%" />
      </>,
    );
    expect(container.querySelector(".skeleton-card")).not.toBeNull();
    expect(container.querySelector(".skeleton-list-row")).not.toBeNull();
    expect(container.querySelector(".skeleton-avatar")).not.toBeNull();
    const textSk = container.lastElementChild as HTMLElement;
    expect(textSk.className).not.toContain("skeleton-card");
    expect(textSk.getAttribute("style")).toBe("width: 60%;");
  });

  it("Field wires label, error and hint accessibly", () => {
    render(
      <Field label={t("classLevel")} htmlFor="cls" error="required">
        <input id="cls" />
      </Field>,
    );
    const label = screen.getByText(t("classLevel"));
    expect(label).toHaveAttribute("for", "cls");
    expect(screen.getByRole("alert")).toHaveTextContent("required");
  });

  it("Field ties the error and the hint to the control it wraps", () => {
    // F-060/A11Y-08: the announced error must also be reachable FROM the
    // field, and the hint announced WITH it -- otherwise a screen reader
    // hears a failure it cannot navigate back to.
    const { rerender } = render(
      <Field label={t("classLevel")} htmlFor="cls" hint="1-6">
        <input id="cls" />
      </Field>,
    );
    const input = screen.getByRole("textbox");
    const hint = screen.getByText("1-6");
    expect(input).toHaveAttribute("aria-describedby", hint.id);
    expect(input).not.toHaveAttribute("aria-invalid");

    rerender(
      <Field label={t("classLevel")} htmlFor="cls" hint="1-6" error="required">
        <input id="cls" />
      </Field>,
    );
    expect(input).toHaveAttribute("aria-invalid", "true");
    // The error replaces the hint, and the description points at the alert.
    const alert = screen.getByRole("alert");
    expect(input).toHaveAttribute("aria-describedby", alert.id);
    expect(screen.queryByText("1-6")).not.toBeInTheDocument();
  });

  it("Segmented is a labelled toggle group: aria-pressed state + onChange", async () => {
    // role=group + aria-pressed, not tablist/tab: these pick a filter and have
    // no tabpanels, so a tablist role promised an arrow-key contract the
    // component never delivered (audit M-17). Plain buttons keep the keyboard
    // promise trivially true.
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        ariaLabel="period"
        value="a"
        onChange={onChange}
        options={[
          { value: "a", label: "A" },
          { value: "b", label: "B" },
        ]}
      />,
    );
    const group = screen.getByRole("group", { name: "period" });
    expect(group).toBeInTheDocument();
    const a = screen.getByRole("button", { name: "A" });
    expect(a).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "B" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await user.click(screen.getByRole("button", { name: "B" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("Avatar renders the first initial with size/tone classes", () => {
    render(<Avatar name="করিমা" size="lg" tone="ai" />);
    const av = screen.getByText("ক");
    expect(av.className).toContain("avatar-lg");
    expect(av.className).toContain("avatar-ai");
  });

  it("Spinner announces the localized loading label by default", () => {
    setLang("bn");
    const { unmount } = render(<Spinner />);
    expect(screen.getByText("লোড হচ্ছে…")).toBeInTheDocument();
    unmount();
    setLang("en");
    render(<Spinner />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});
