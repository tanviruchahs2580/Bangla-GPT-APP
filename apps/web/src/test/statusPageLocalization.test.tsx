/**
 * FE-FIX-017: /status rendered the API's English machine strings.
 *
 * `routers/system.py` answers `name="cache"`, `detail="shared cache reachable"`,
 * `"no LLM provider configured"` — a deliberate machine contract — and the page
 * printed them verbatim, which made the status page (linked from every footer)
 * the only English left in the Bangla product. The client maps them now
 * (`lib/roles.ts` pattern) and names anything unmapped generically instead of
 * leaking the server's words.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import StatusPage from "../pages/StatusPage";
import { setLang, t } from "../i18n";
import type { StatusOut } from "../types";

const apiMock = vi.hoisted(() => ({ getStatus: vi.fn() }));

vi.mock("../api", () => apiMock);

const STATUS: StatusOut = {
  status: "degraded",
  components: [
    { name: "database", ok: true, detail: "queries responding" },
    { name: "cache", ok: true, detail: "shared cache reachable" },
    { name: "assistant", ok: false, detail: "no LLM provider configured" },
    { name: "curriculum", ok: true, detail: "retrieval index loaded" },
  ],
  checked_at: "2026-11-10T10:00:00",
};

function renderPage() {
  return render(
    <MemoryRouter>
      <StatusPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  setLang("bn");
  apiMock.getStatus.mockResolvedValue(STATUS);
});

describe("status page localization", () => {
  it("maps component names and details to the active language", async () => {
    renderPage();
    await screen.findByRole("status");

    expect(screen.getByText(t("statusCompCache"))).toBeTruthy();
    expect(screen.getByText(t("statusDetailCacheShared"))).toBeTruthy();
    expect(screen.getByText(t("statusDetailNoProvider"))).toBeTruthy();
    expect(screen.getByText(t("statusCompCurriculum"))).toBeTruthy();
  });

  it("leaves no raw server string on the page", async () => {
    renderPage();
    await screen.findByRole("status");

    for (const raw of [
      "cache",
      "assistant",
      "curriculum",
      "shared cache reachable",
      "no LLM provider configured",
      "queries responding",
      "retrieval index loaded",
    ]) {
      expect(screen.queryByText(raw)).toBeNull();
    }
  });

  it("names a detail this build has no copy for instead of leaking it", async () => {
    apiMock.getStatus.mockResolvedValue({
      ...STATUS,
      components: [
        {
          name: "cache",
          ok: false,
          detail: "3 consecutive provider calls failed",
        },
        { name: "brand-new-lane", ok: true, detail: "something unforeseen" },
      ],
    });
    renderPage();
    await screen.findByRole("status");

    // The counted provider sentence is matched, not looked up: its count is a
    // quantity and takes Bangla digits.
    expect(
      screen.getByText(t("statusDetailProviderFailed", { n: 3 })),
    ).toBeTruthy();
    expect(screen.queryByText("something unforeseen")).toBeNull();
    expect(screen.getByText(t("statusCompUnknown"))).toBeTruthy();
    expect(screen.getByText(t("statusDetailUnknown"))).toBeTruthy();
  });
});
