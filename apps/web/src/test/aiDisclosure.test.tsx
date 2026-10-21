/**
 * AUD-B-30: AI-use / third-party-LLM disclosure in the product.
 *
 * The audit found no user-visible statement that answers come from an
 * external model. The privacy policy now carries a bn+en section naming the
 * processor (Google Gemini) and what is sent, and the register screen shows
 * the short notice next to the consent block. This test pins both so the
 * disclosure cannot be deleted silently.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import LegalPage from "../pages/LegalPage";
import RegisterPage from "../pages/RegisterPage";
import { AuthProvider } from "../AuthContext";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  register: vi.fn(),
  login: vi.fn(),
  verifyEmail: vi.fn(),
  resendVerification: vi.fn(),
  fetchMe: vi.fn(),
  // AUD-G-15: AuthProvider reads the stored session before its first commit.
  getToken: vi.fn(() => null),
  logout: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}));

vi.mock("../api", () => apiMock);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

describe("AI-use disclosure (AUD-B-30)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    apiMock.setUnauthorizedHandler.mockReturnValue(() => undefined);
    apiMock.fetchMe.mockResolvedValue(null);
    apiMock.logout.mockReturnValue(undefined);
  });

  it("names the third-party model in the privacy policy in both languages", () => {
    render(<LegalPage kind="privacy" />);
    // Once in the Bangla body and once in the English body.
    expect(screen.getAllByText(/Google Gemini/)).toHaveLength(2);
    // The Bangla heading is rendered too, so the section is visible to a
    // Bangla-first reader rather than only in the muted English line.
    expect(screen.getByText(/AI ব্যবহার ও তৃতীয় পক্ষের মডেল/)).toBeTruthy();
    expect(
      screen.getByText(/আপনার নাম, ইমেইল বা ফোন নম্বর পাঠানো হয় না/),
    ).toBeTruthy();
  });

  it("shows the short notice on the register screen", () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <MemoryRouter>
            <RegisterPage />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    );
    const notice = screen.getByTestId("ai-disclosure");
    expect(notice.textContent).toBe(t("aiDisclosureShort"));
    // The copy actually talks about the model, not an empty placeholder.
    expect(notice.textContent).toMatch(/AI/);
  });
});
