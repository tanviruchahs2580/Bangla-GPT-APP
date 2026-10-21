/**
 * AUD-B-01: the privacy policy told users their password was hashed with
 * PBKDF2 while the API hashes with Argon2id
 * (apps/api/src/bangla_gpt_api/auth/security.py). A false security claim on a
 * children's platform is worse than no claim, so the visible copy is pinned to
 * the algorithm the API actually runs.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LegalPage from "../pages/LegalPage";

describe("privacy policy security copy (AUD-B-01)", () => {
  it("names Argon2id in both languages and never the old algorithm", () => {
    render(<LegalPage kind="privacy" />);
    // Once in the Bangla body and once in the English body.
    expect(screen.getAllByText(/Argon2id/)).toHaveLength(2);
    expect(screen.queryByText(/PBKDF2/i)).toBeNull();
  });
});
