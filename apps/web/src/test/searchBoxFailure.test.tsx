/**
 * FE-FIX-001: a failed search is not "no results".
 *
 * The dropdown used to catch the request into `{hits: []}`, so an outage
 * rendered as the confident sentence "কোনো ফলাফল নেই" — a statement about the
 * content — with no error and nothing to press. The failure now has copy and a
 * retry, and the retry re-asks.
 *
 * The same file pins the trust rule: `hit.href` is server-supplied, so it is
 * validated against the in-app allowlist before it is rendered or navigated to
 * (`lib/safeHref`, the rule NotificationBell already applied).
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SearchBox } from "../components/SearchBox";
import { t } from "../i18n";
import type { SearchResponse } from "../types";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("../api", () => apiMock);

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="probe">{loc.pathname + loc.search}</div>;
}

function renderBox() {
  return render(
    <MemoryRouter initialEntries={["/student"]}>
      <SearchBox />
      <LocationProbe />
    </MemoryRouter>,
  );
}

function hits(...hrefs: string[]): SearchResponse {
  return {
    query: "kos",
    ask_action: false,
    hits: hrefs.map((href, i) => ({
      kind: "chapter",
      title: `Chapter ${i}`,
      subtitle: "Biggan",
      href,
      score: 1,
    })),
  };
}

describe("search failure is named, not disguised as an empty result", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows an honest error with a working retry instead of 'no results'", async () => {
    const user = userEvent.setup();
    apiMock.get.mockRejectedValueOnce(new Error("502"));
    renderBox();
    const box = screen.getByRole("combobox");
    await user.type(box, "kos");

    expect(await screen.findByText(t("searchFailed"))).toBeTruthy();
    // The false statement must be gone: this is the defect.
    expect(screen.queryByText(t("searchNoResults"))).toBeNull();

    // ...and the retry re-asks rather than leaving the student stuck.
    apiMock.get.mockResolvedValueOnce(hits("/student/learn/science/Kosh"));
    await user.click(screen.getByRole("button", { name: t("retry") }));
    expect(await screen.findByText("Chapter 0")).toBeTruthy();
    expect(screen.queryByText(t("searchFailed"))).toBeNull();
    expect(apiMock.get).toHaveBeenCalledTimes(2);
  });

  it("does not navigate to a hit whose href is not an in-app route", async () => {
    const user = userEvent.setup();
    apiMock.get.mockResolvedValue(
      hits("https://evil.example/steal", "javascript:alert(1)"),
    );
    renderBox();
    await user.type(screen.getByRole("combobox"), "kos");

    // Neither hit is offered, and the reason is said out loud rather than the
    // options disappearing silently.
    expect(await screen.findByText(t("searchFailed"))).toBeTruthy();
    expect(screen.queryByText("Chapter 0")).toBeNull();
    expect(screen.queryByText("Chapter 1")).toBeNull();
    expect(screen.getByTestId("probe").textContent).toBe("/student");
  });

  it("still opens the query via the tutor action and navigates a valid hit", async () => {
    const user = userEvent.setup();
    apiMock.get.mockResolvedValue({
      ...hits("/student/learn/science/Kosh?class=6"),
      ask_action: true,
    });
    renderBox();
    await user.type(screen.getByRole("combobox"), "kos");
    await user.click(await screen.findByText("Chapter 0"));
    await waitFor(() =>
      expect(screen.getByTestId("probe").textContent).toBe(
        "/student/learn/science/Kosh?class=6",
      ),
    );
  });
});
