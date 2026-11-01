/**
 * F-IV2-3: a leaked guardian invite code was not revocable from the product.
 * The create response now carries the database id (what the DELETE route
 * revokes by) and the card lists live codes so an id from an earlier visit
 * is reachable too. These tests pin both paths to the API calls they must
 * make.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ParentInviteCard from "../components/ParentInviteCard";
import { setLang, t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  generateInviteCode: vi.fn(),
  getLiveInviteCodes: vi.fn(),
  revokeInviteCode: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
}));

function renderCard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ParentInviteCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  setLang("en");
  apiMock.getLiveInviteCodes.mockResolvedValue([]);
  apiMock.revokeInviteCode.mockResolvedValue(undefined);
});

describe("parent invite card", () => {
  it("revokes a code created in this visit by the id from the response", async () => {
    apiMock.generateInviteCode.mockResolvedValue({
      id: 42,
      code: "BGPT-0123456789ABCDEF",
      expires_in_minutes: 1440,
    });
    renderCard();

    await userEvent.click(
      screen.getByRole("button", { name: t("parentInviteGenerate") }),
    );
    await screen.findByText("BGPT-0123456789ABCDEF");
    await userEvent.click(
      screen.getByRole("button", {
        name: `${t("parentInviteRevoke")}: BGPT-0123456789ABCDEF`,
      }),
    );

    await waitFor(() =>
      expect(apiMock.revokeInviteCode).toHaveBeenCalledWith(42),
    );
    expect(await screen.findByText(t("parentInviteRevoked"))).toBeTruthy();
  });

  it("lists live codes from an earlier visit and revokes the listed id", async () => {
    apiMock.getLiveInviteCodes.mockResolvedValue([
      {
        id: 7,
        created_at: "2026-10-30T10:00:00",
        expires_at: "2026-10-31T10:00:00",
      },
    ]);
    renderCard();

    const revoke = await screen.findByRole("button", {
      name: new RegExp(`^${t("parentInviteRevoke")}:`),
    });
    await userEvent.click(revoke);
    await waitFor(() =>
      expect(apiMock.revokeInviteCode).toHaveBeenCalledWith(7),
    );
  });
});
