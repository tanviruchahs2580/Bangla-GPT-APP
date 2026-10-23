/**
 * The password-reset and code-verification page had no tests at all —
 * named in the audit as one of the three untested surfaces (routes, SW,
 * reset). It also hosts the W-1 fix's most user-visible path: `reset`
 * hands `friendlyError` a bare machine code, and before the fix every code
 * on this screen fell through to "something went wrong". The invalid-token
 * case below is the regression test for that.
 */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import ForgotResetPage from "../pages/ForgotResetPage";
import { setLang, t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  forgotPassword: vi.fn(() => Promise.resolve()),
  resetPassword: vi.fn(() => Promise.resolve()),
  verifyEmail: vi.fn(() => Promise.resolve()),
}));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    ...apiMock,
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  setLang("bn");
});


/** The tab strip button and the form submit share an accessible name; the
 * submit (inside the form) is last in DOM order, which is the only one any
 * test needs to press (the page always opens on the forgot tab). */
function submitButton() {
  return screen.getAllByRole("button", { name: t("resetTitle") }).at(-1)!;
}

describe("ForgotResetPage", () => {
  it("requests a reset code and shows the sent notice", async () => {
    render(<ForgotResetPage />);
    await userEvent.type(
      screen.getByLabelText(t("email")),
      "parent@example.test",
    );
    await userEvent.click(submitButton());

    await waitFor(() =>
      expect(apiMock.forgotPassword).toHaveBeenCalledWith("parent@example.test"),
    );
    expect(await screen.findByText(t("forgotSent"))).toBeTruthy();
  });

  it("submits code + new password through the real reset call", async () => {
    render(<ForgotResetPage />);
    await userEvent.type(
      screen.getByLabelText(t("email")),
      "parent@example.test",
    );
    await userEvent.click(submitButton());

    await userEvent.type(
      await screen.findByLabelText(t("locResetCode")),
      "reset-code-1234567890",
    );
    await userEvent.type(
      screen.getByLabelText(t("password")),
      "BrandNewPass!234",
    );
    await userEvent.click(submitButton());

    await waitFor(() =>
      expect(apiMock.resetPassword).toHaveBeenCalledWith(
        "reset-code-1234567890",
        "BrandNewPass!234",
      ),
    );
  });

  it("shows the coded copy for a rejected code, not the generic fallback", async () => {
    apiMock.resetPassword.mockRejectedValueOnce(
      new ApiError(400, "bad", "invalid_token"),
    );
    render(<ForgotResetPage />);
    await userEvent.type(screen.getByLabelText(t("email")), "x@example.test");
    await userEvent.click(submitButton());
    await userEvent.type(
      await screen.findByLabelText(t("locResetCode")),
      "expired-code-000000",
    );
    await userEvent.type(screen.getByLabelText(t("password")), "BrandNewPass!234");
    await userEvent.click(submitButton());

    // errInvalidToken, NOT errGeneric: the string-code branch of
    // friendlyError is exactly what this page depends on.
    expect(await screen.findByText(t("errInvalidToken"))).toBeTruthy();
  });
});
