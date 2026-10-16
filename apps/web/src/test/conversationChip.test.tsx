import { describe, expect, it, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConversationChip } from "../components/ConversationChip";

// A11Y-02: the open, rename and delete controls were spans with role="button"
// nested inside the chip's own button -- a button inside a button, reported by
// axe as nested-interactive and indistinguishable to a keyboard user.
describe("conversation chip", () => {
  afterEach(cleanup);

  it("keeps every control a sibling, never nested inside another control", () => {
    const { container } = render(
      <ConversationChip
        title="কোষ"
        active
        onOpen={() => {}}
        onRename={() => {}}
        onDelete={() => {}}
      />,
    );
    const buttons = container.querySelectorAll("button");
    expect(buttons.length).toBe(3);
    for (const b of Array.from(buttons)) {
      expect(b.querySelector("button, [role='button']")).toBeNull();
    }
    // The container itself is not a control.
    expect(container.firstElementChild?.getAttribute("role")).toBeNull();
    expect(container.querySelector("span[role='button']")).toBeNull();
  });

  it("opens, renames and deletes through separate controls", async () => {
    const onOpen = vi.fn();
    const onRename = vi.fn();
    const onDelete = vi.fn();
    render(
      <ConversationChip
        title="কোষ"
        active
        onOpen={onOpen}
        onRename={onRename}
        onDelete={onDelete}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "কোষ" }));
    await userEvent.click(
      screen.getByRole("button", { name: "নাম পরিবর্তন করুন" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "চ্যাট মুছুন" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("offers rename only for the conversation that is open", () => {
    render(
      <ConversationChip
        title="কোষ"
        active={false}
        onOpen={() => {}}
        onRename={() => {}}
        onDelete={() => {}}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "নাম পরিবর্তন করুন" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "চ্যাট মুছুন" })).toBeTruthy();
  });
});
