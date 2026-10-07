import { describe, expect, it } from "vitest";
import { friendlyError } from "../errors";
import { t } from "../i18n";

describe("friendlyError", () => {
  it("maps machine codes to localized copy", () => {
    expect(
      friendlyError({ code: "email_unverified", message: "x" }).action,
    ).toBe("resend-verification");
    expect(
      friendlyError({ code: "rate_limited", message: "x" }).text,
    ).toContain("মিনিট");
  });

  it("maps login-infrastructure codes to retry/mfa copy (no generic dead-end)", () => {
    expect(friendlyError({ code: "mfa_required" }).action).toBe("mfa");
    expect(friendlyError({ code: "bad_mfa_code" }).action).toBe("mfa");
    for (const code of [
      "bad_gateway",
      "service_unavailable",
      "api_origin_unconfigured",
      "verify_failed",
    ]) {
      const out = friendlyError({ code, message: code });
      expect(out.action).toBe("retry");
      expect(out.text.length).toBeGreaterThan(5);
    }
    expect(
      friendlyError({ code: "api_base_unconfigured" }).text.length,
    ).toBeGreaterThan(5);
  });

  it("falls back to generic copy for unknown codes", () => {
    const out = friendlyError({ code: "zzz_unknown", message: "weird" });
    expect(out.text.length).toBeGreaterThan(5);
  });

  it("handles legacy string details and nulls", () => {
    expect(friendlyError(null).text).toBeTruthy();
    expect(friendlyError("Email already registered").text).toBeTruthy();
  });
});

describe("i18n", () => {
  it("defaults to Bengali with interpolation support", () => {
    const out = t("partialQuizNote", { got: 4, want: 5 });
    expect(out).toContain("4");
    expect(out).toContain("5");
  });
});
