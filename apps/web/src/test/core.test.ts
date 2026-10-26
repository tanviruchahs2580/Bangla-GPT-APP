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

  it("reports a dead/unconfigured API origin as not-connected, not as a busy server", () => {
    const busy = t("errServiceUnavailable");
    for (const code of ["api_origin_unreachable", "api_origin_unconfigured"]) {
      const out = friendlyError({ code, message: code });
      // A dead origin does not recover on its own; "busy, try again shortly"
      // would promise something that cannot happen.
      expect(out.text).not.toBe(busy);
      expect(out.text).toBe(t("errApiOriginDown"));
      expect(out.action).toBe("retry");
    }
  });

  it("gives an unreadable photo its own advice, not the generic line", () => {
    // The API answers 422 image_invalid when the server could not decode or
    // re-encode an attached image (providers/image_safety.py). The client's
    // own checks answer first for size and type, so this code means "the file
    // itself was unusable" and the copy has to say which photo to send next.
    const out = friendlyError({ code: "image_invalid", message: "x" });
    expect(out.text).toBe(t("errImageInvalid"));
    expect(out.action).toBe("retry");
  });

  it("falls back to generic copy for unknown codes", () => {
    const out = friendlyError({ code: "zzz_unknown", message: "weird" });
    expect(out.text.length).toBeGreaterThan(5);
  });

  it("handles legacy string details and nulls", () => {
    expect(friendlyError(null).text).toBeTruthy();
    expect(friendlyError("Email already registered").text).toBeTruthy();
  });

  it("maps a bare machine code string, not just an object", () => {
    // The register / verify / reset screens hold only `err.code`, so they pass
    // the code on its own: `friendlyError((err as {code?: string}).code)`. The
    // string branch used to consult LEGACY_BN only, so every one of those fell
    // through to "something went wrong" while the same code inside an object
    // produced the right copy.
    expect(friendlyError("rate_limited").text).toBe(t("errRateLimited"));
    expect(friendlyError("rate_limited").text).not.toBe(t("errGeneric"));
    expect(friendlyError("invalid_token").text).toBe(t("errInvalidToken"));
    expect(friendlyError("email_unverified").action).toBe(
      "resend-verification",
    );
  });

  it("still maps legacy Bengali detail strings, which are not codes", () => {
    expect(
      friendlyError("অনেকবার চেষ্টা হয়েছে। এক মিনিট অপেক্ষা করুন।").text,
    ).toBe(t("errRateLimited"));
    expect(friendlyError("এটি করার অনুমতি নেই।").text).toBe(t("errNotAllowed"));
  });
});

describe("i18n", () => {
  it("defaults to Bengali with interpolation support", () => {
    const out = t("partialQuizNote", { got: 4, want: 5 });
    expect(out).toContain("4");
    expect(out).toContain("5");
  });
});
