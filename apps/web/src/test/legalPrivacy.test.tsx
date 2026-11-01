/**
 * F-041 / F-018 (PRIV-07, LEGAL-05): the /privacy copy is the user-facing
 * statement of what the app actually does, and it must not drift from the
 * shipped behaviour again. It claimed PBKDF2 after the Argon2id switch
 * (auth/security.py) and omitted the guardian phone, the LLM processor, the
 * 180-day chat retention and error monitoring. This pins each disclosure in
 * both languages; the wording itself still needs owner/legal review.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import LegalPage from "../pages/LegalPage";
import { setLang } from "../i18n";

/** One pattern per disclosure, Bangla line and English line of the page. */
const DISCLOSURES: Array<[string, RegExp]> = [
  ["Argon2id (bn)", /Argon2id/],
  ["Argon2id (en)", /Passwords are hashed with Argon2id/],
  ["guardian phone (bn)", /অভিভাবকের ফোন নম্বর/],
  ["guardian phone (en)", /guardian phone number is stored/],
  ["LLM processor (bn)", /জেমিনি/],
  ["LLM processor (en)", /Google.s Gemini model API/],
  ["chat retention (bn)", /১৮০ দিন/],
  ["chat retention (en)", /kept for up to 180 days/],
  ["error monitoring (bn)", /Sentry/],
  ["error monitoring (en)", /error events to Sentry/],
];

describe("privacy page disclosures (F-041/F-018)", () => {
  beforeEach(() => {
    setLang("bn");
  });

  it.each(DISCLOSURES)("states %s", (_label, pattern) => {
    render(<LegalPage kind="privacy" />);
    const page = screen.getByText(/Privacy Policy/).closest("main");
    expect(page).not.toBeNull();
    expect(page as HTMLElement).toHaveTextContent(pattern);
  });

  it("no longer names a hashing algorithm the app does not use", () => {
    render(<LegalPage kind="privacy" />);
    const page = screen
      .getByText(/Privacy Policy/)
      .closest("main") as HTMLElement;
    expect(page).not.toHaveTextContent(/PBKDF2/);
  });
});
