/**
 * FE-FIX-010: the AI-quality card rendered NOTHING while loading and again on
 * an unexpected payload, so the panel whose purpose is auditing answer quality
 * was indistinguishable from a panel with nothing to say. Both states are
 * named now, and the unreadable one carries a retry.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AiQualityCard } from "../components/admin/AiQualityCard";
import { setLang, t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  getAdminAiQuality: vi.fn(),
}));

vi.mock("../api", () => apiMock);

beforeEach(() => {
  vi.clearAllMocks();
  setLang("en");
});

describe("AI quality card states", () => {
  it("says it is loading rather than rendering nothing", async () => {
    let resolve!: (value: unknown) => void;
    apiMock.getAdminAiQuality.mockImplementation(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    render(<AiQualityCard />);

    expect(screen.getByRole("status").textContent).toBe(t("loading"));
    resolve({
      days: 30,
      answers_total: 4,
      grounded_count: 4,
      ungrounded_count: 0,
      low_confidence_count: 1,
      thumbs_up: 0,
      thumbs_down: 0,
      refusals_total: 0,
      refusals_by_reason: {},
      by_model: {},
    });
    expect(await screen.findByText(t("aiqAnswers"))).toBeTruthy();
  });

  it("says the response could not be read, with a retry", async () => {
    apiMock.getAdminAiQuality.mockResolvedValue({ unexpected: true });
    render(<AiQualityCard />);

    expect(await screen.findByText(t("aiqUnreadable"))).toBeTruthy();
    expect(screen.getByRole("button", { name: t("retry") })).toBeTruthy();
  });

  it("keeps the honest retryable error on a failed fetch", async () => {
    apiMock.getAdminAiQuality.mockRejectedValue(new Error("503"));
    render(<AiQualityCard />);

    expect(await screen.findByText(t("errorGeneric"))).toBeTruthy();
    expect(screen.getByRole("button", { name: t("retry") })).toBeTruthy();
  });
});
