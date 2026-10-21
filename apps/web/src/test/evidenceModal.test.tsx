import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { t } from "../i18n";
import {
  SOURCE,
  askOneQuestion,
  renderTutorPage,
  wireTutorMocks,
} from "./tutorPageMock";

// The hoisted surface must stay per-file: vi.mock factories run before module
// imports, so a shared module crashes this vitest build's worker (measured;
// see the harness docstring).
const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));
const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));
vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

function sourceChip(): HTMLElement {
  const chip = screen
    .getAllByRole("button")
    .find((b) => b.className.includes("source-chip"));
  if (!chip) throw new Error("source chip button not found");
  return chip;
}

describe("evidence modal", () => {
  beforeEach(() => wireTutorMocks(apiMock, authMock));

  it("source chip opens the evidence modal with the sanitized excerpt and path", async () => {
    const user = userEvent.setup();
    renderTutorPage();
    await askOneQuestion(user);

    // The chip advertises the evidence action through its accessible name.
    const chip = await waitFor(sourceChip);
    expect(chip.getAttribute("aria-label")).toContain(t("evidenceTitle"));
    await user.click(chip);

    const dialog = await screen.findByRole("dialog");
    // Full sanitized excerpt shown, not just the short citation label.
    expect(within(dialog).getByText(SOURCE.excerpt)).toBeInTheDocument();
    // Book / chapter / section breadcrumb path.
    expect(dialog.textContent).toContain("Biggan");
    expect(dialog.textContent).toContain("Cell-Ki");
    // Raw provider markup never reaches the UI.
    expect(dialog.textContent).not.toContain("<evidence>");
    expect(dialog.textContent).not.toContain("</evidence>");
    expect(dialog.textContent).not.toContain("<user_question>");
  });

  it("closes the modal via the close button", async () => {
    const user = userEvent.setup();
    renderTutorPage();
    await askOneQuestion(user);
    await user.click(await waitFor(sourceChip));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: t("close") }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
