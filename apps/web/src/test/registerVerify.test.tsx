import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import RegisterPage from "../pages/RegisterPage";
import { AuthProvider } from "../AuthContext";
import { t } from "../i18n";

// The production posture mails a verification code and refuses to sign the
// account in until it is redeemed. The register screen used to answer that
// with a sentence and nothing else, so a new user could not finish signing
// up: the only code entry lived on the forgot-password page.
const apiMock = vi.hoisted(() => ({
  register: vi.fn(),
  login: vi.fn(),
  verifyEmail: vi.fn(),
  resendVerification: vi.fn(),
  fetchMe: vi.fn(),
  logout: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}));

vi.mock("../api", () => apiMock);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function renderRegister() {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter>
          <RegisterPage />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

async function fillAndSubmit() {
  await userEvent.selectOptions(screen.getByLabelText(t("role")), "student");
  await userEvent.type(screen.getByLabelText(t("name")), "পরীক্ষা শিক্ষার্থী");
  await userEvent.type(
    screen.getByLabelText(t("email")),
    "qa.verify@example.com",
  );
  await userEvent.type(screen.getByLabelText(t("password")), "QaVerify!2026");
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("button", { name: t("register") }));
}

describe("register screen verification step", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    apiMock.setUnauthorizedHandler.mockReturnValue(() => undefined);
    apiMock.fetchMe.mockResolvedValue(null);
    apiMock.logout.mockReturnValue(undefined);
    apiMock.register.mockResolvedValue({
      user_id: 1,
      role: "student",
      profile_id: 1,
    });
  });

  it("offers the code entry when the account needs verification", async () => {
    const unverified = Object.assign(new Error("verify"), {
      code: "email_unverified",
    });
    apiMock.login.mockRejectedValueOnce(unverified);
    renderRegister();
    await fillAndSubmit();

    const field = await screen.findByLabelText(t("verifyTitle"));
    expect(field).toBeTruthy();
    expect((field as HTMLInputElement).id).toBe("vcode");
    expect(screen.getByRole("button", { name: t("verifyBtn") })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: t("resendVerification") }),
    ).toBeTruthy();
  });

  it("verifies the code and signs the new account in", async () => {
    const unverified = Object.assign(new Error("verify"), {
      code: "email_unverified",
    });
    apiMock.login.mockRejectedValueOnce(unverified).mockResolvedValueOnce({
      me: {
        id: 1,
        email: "qa.verify@example.com",
        role: "student",
        name: "পরীক্ষা",
      },
      mustChangePassword: false,
    });
    apiMock.verifyEmail.mockResolvedValue(undefined);

    renderRegister();
    await fillAndSubmit();
    await userEvent.type(
      await screen.findByLabelText(t("verifyTitle")),
      "a".repeat(24),
    );
    await userEvent.click(screen.getByRole("button", { name: t("verifyBtn") }));

    await waitFor(() => expect(apiMock.verifyEmail).toHaveBeenCalledTimes(1));
    expect(apiMock.verifyEmail.mock.calls[0][0]).toBe("a".repeat(24));
    await waitFor(() => expect(apiMock.login).toHaveBeenCalledTimes(2));
  });
});
