/** E2: the EmptyState primitive — the shared shape for "this space is
 *  empty". The static guard (e2LoadingGuard.test.ts) pins adoption across
 *  pages; here we pin the behaviour: title and body render, the action slot
 *  is the caller's own control and fires, the optional parts disappear
 *  cleanly when omitted, and the icon stays decorative (the .empty-mark
 *  contract — the title carries the meaning, never the glyph). */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BookOpen } from "lucide-react";
import { EmptyState } from "../components/ui";
import { t } from "../i18n";

describe("EmptyState", () => {
  it("renders title, body and action, and fires the action click", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <EmptyState
        icon={BookOpen}
        title={t("noDocumentsYet")}
        body={t("asmCreateInCreate")}
        action={
          <button type="button" onClick={onOpen}>
            {t("createHubTitle")}
          </button>
        }
      />,
    );

    expect(screen.getByText(t("noDocumentsYet"))).toBeInTheDocument();
    expect(screen.getByText(t("asmCreateInCreate"))).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: t("createHubTitle") }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("keeps the icon decorative (aria-hidden), like .empty-mark", () => {
    const { container } = render(
      <EmptyState icon={BookOpen} title={t("noDocumentsYet")} />,
    );
    const icon = container.querySelector(".empty-icon");
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("omits the optional parts cleanly when not given", () => {
    const { container } = render(<EmptyState title={t("noDocumentsYet")} />);
    expect(container.querySelector(".empty-icon")).toBeNull();
    expect(container.querySelector(".empty-state-body")).toBeNull();
    expect(container.querySelector(".empty-state-action")).toBeNull();
    expect(container.querySelector(".empty-state-title")?.textContent).toBe(
      t("noDocumentsYet"),
    );
  });

  it("size sm renders the compact variant", () => {
    const { container } = render(
      <EmptyState size="sm" title={t("noDocumentsYet")} />,
    );
    expect(container.firstElementChild).toHaveClass("empty-state");
    expect(container.firstElementChild).toHaveClass("empty-state-sm");
  });
});
