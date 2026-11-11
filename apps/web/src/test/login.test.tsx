import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import LoginPage from "../pages/LoginPage";
import { AuthProvider } from "../AuthContext";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  login: vi.fn(),
  mfaChallenge: vi.fn(),
  fetchMe: vi.fn(),
  logout: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
  resendVerification: vi.fn(),
}));

vi.mock("../api", () => apiMock);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function renderLogin() {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("LoginPage UX contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.fetchMe.mockResolvedValue(null);
    apiMock.logout.mockReturnValue(undefined);
    apiMock.setUnauthorizedHandler.mockImplementation(() => () => undefined);
    localStorage.clear();
  });

  it("renders localized form with autocomplete attributes", () => {
    renderLogin();
    const email = screen.getByLabelText(/ইমেইল|Email/i);
    expect(email).toHaveAttribute("autocomplete", "email");
    expect(
      screen.getByRole("button", { name: /লগইন|Log in/i }),
    ).toBeInTheDocument();
  });

  it("surfaces the machine code as friendly copy on failure", async () => {
    apiMock.login.mockRejectedValue(
      Object.assign(new Error("Email verification required"), {
        code: "email_unverified",
      }),
    );
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText("ইমেইল"), "a@b.com");
    await user.type(screen.getByLabelText(/পাসওয়ার্ড/), "longpassword1");
    await user.click(screen.getByRole("button", { name: /লগইন|Log in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("যাচাই");
    expect(apiMock.login).toHaveBeenCalledOnce();
  });

  it("shows the OTP step when login answers mfa_required", async () => {
    apiMock.login.mockRejectedValue(
      Object.assign(new Error("two-step verification required"), {
        code: "mfa_required",
        rawDetail: { mfa_token: "step-up-token" },
      }),
    );
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText("ইমেইল"), "a@b.com");
    await user.type(screen.getByLabelText(/পাসওয়ার্ড/), "longpassword1");
    await user.click(screen.getByRole("button", { name: /লগইন|Log in/i }));
    expect(
      await screen.findByText(/দুই ধাপের যাচাই|Two-step/i),
    ).toBeInTheDocument();
  });

  it("offers resend-verification as an action, not a link to another page", async () => {
    // FE-FIX (false affordance): this control was `<a href="/forgot">` with an
    // intercepted click. A plain click resent the verification mail, but a
    // middle-click, "open in new tab" or a JS-less load navigated to the
    // password-reset page -- and assistive tech announced it as a link. The
    // RegisterPage equivalent was already a button.
    apiMock.login.mockRejectedValue(
      Object.assign(new Error("Email verification required"), {
        code: "email_unverified",
      }),
    );
    apiMock.resendVerification.mockResolvedValue(undefined);
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText("ইমেইল"), "a@b.com");
    await user.type(screen.getByLabelText(/পাসওয়ার্ড/), "longpassword1");
    await user.click(screen.getByRole("button", { name: /লগইন|Log in/i }));

    const resend = await screen.findByRole("button", {
      name: t("resendVerification"),
    });
    // Inside a <form>: it must not be able to submit it.
    expect(resend).toHaveAttribute("type", "button");
    expect(
      screen.queryByRole("link", { name: t("resendVerification") }),
    ).toBeNull();

    await user.click(resend);
    await waitFor(() =>
      expect(apiMock.resendVerification).toHaveBeenCalledWith("a@b.com"),
    );
  });
});
