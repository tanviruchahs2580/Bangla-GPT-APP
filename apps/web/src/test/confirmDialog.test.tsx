/** E1: the ConfirmDialog primitive — the accessible replacement for the
 *  window.confirm/window.prompt calls the interaction-integrity wave removed.
 *  The dialog is built ON Modal, so the trap/Escape/portal semantics are
 *  asserted there (uiPrimitives.test.tsx); here we pin the confirm/cancel
 *  contract and the tones, plus the new i18n keys in BOTH languages. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "../components/ui";
import { setLang, t } from "../i18n";

function Harness({
  onConfirm,
  onClose,
  tone = "danger",
}: {
  onConfirm: () => void;
  onClose: () => void;
  tone?: "danger" | "default";
}) {
  return (
    <ConfirmDialog
      open
      tone={tone}
      title={t("deleteChatTitle")}
      body={t("deleteChatBody")}
      confirmLabel={t("deleteChatConfirmAction")}
      onClose={onClose}
      onConfirm={onConfirm}
    />
  );
}

afterEach(() => {
  // The suite's shared language state: leave bn (the product default) behind.
  setLang("bn");
});

describe("ConfirmDialog", () => {
  it("renders the dialog with danger tone and fires onConfirm from the confirm button", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<Harness onConfirm={onConfirm} onClose={onClose} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText(t("deleteChatTitle"))).toBeInTheDocument();
    expect(screen.getByText(t("deleteChatBody"))).toBeInTheDocument();

    const confirm = screen.getByRole("button", {
      name: t("deleteChatConfirmAction"),
    });
    // danger tone paints the destructive action with the danger variant.
    expect(confirm.className).toContain("btn-danger");
    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    // Confirming is the caller's decision to close: the primitive must not
    // close on its own (the tutor page closes it before running the delete).
    expect(onClose).not.toHaveBeenCalled();
  });

  it("cancel closes without confirming", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<Harness onConfirm={onConfirm} onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: t("cancel") }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("the default tone renders the primary variant and the default labels", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <ConfirmDialog
        open
        title={t("confirmTitle")}
        body="body"
        onClose={onClose}
        onConfirm={onConfirm}
      />,
    );
    const confirm = screen.getByRole("button", { name: t("confirmAction") });
    expect(confirm.className).not.toContain("btn-danger");
    expect(confirm.className).toContain("btn-primary");
    // The shared বাতিল/Cancel key is the default cancel label.
    expect(
      screen.getByRole("button", { name: t("cancel") }),
    ).toBeInTheDocument();
  });

  it("renders nothing while closed", () => {
    render(
      <ConfirmDialog
        open={false}
        title="t"
        body="b"
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("E1 i18n keys resolve in both languages", () => {
  const KEYS = [
    "confirmTitle",
    "confirmAction",
    "deleteChatTitle",
    "deleteChatBody",
    "deleteChatConfirmAction",
    "impTitle",
    "impBody",
    "impConfirm",
  ] as const;

  it("every new key resolves to real copy under bn and en", () => {
    for (const lang of ["bn", "en"] as const) {
      setLang(lang);
      for (const key of KEYS) {
        const value = t(key);
        expect(value, `${key} under ${lang}`).not.toBe(key);
        expect(value.trim().length, `${key} under ${lang}`).toBeGreaterThan(0);
      }
    }
  });

  it("carries the specified Bangla copy for the two migrated flows", () => {
    setLang("bn");
    // Impersonation: the dialog must name the action and say it is audited.
    expect(t("impTitle")).toBe("অন্য ব্যবহারকারী হিসেবে প্রবেশ");
    expect(t("impBody")).toContain("নিরীক্ষা");
    expect(t("impConfirm")).toBe("প্রবেশ করুন");
    // Chat delete: question, consequence, button.
    expect(t("deleteChatTitle")).toBe("কথোপকথন মুছবেন?");
    expect(t("deleteChatBody")).toBe(
      "এই কথোপকথন ও এর সব বার্তা মুছে যাবে। এটি ফিরিয়ে আনা যাবে না।",
    );
    expect(t("deleteChatConfirmAction")).toBe("মুছুন");
    // The generic pair.
    expect(t("confirmTitle")).toBe("নিশ্চিত করবেন?");
    expect(t("cancel")).toBe("বাতিল");
  });
});
