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

  it("sends a Bangla name through unchanged (G-06)", async () => {
    // "Bangla names accepted" was untested: the field is free text, and every
    // step between it and the API (trim, validation, normalisation) is a place
    // a conjunct could be mangled or rejected. The name typed in the form must
    // be the name in the request body.
    renderRegister();
    await fillAndSubmit();

    await waitFor(() => expect(apiMock.register).toHaveBeenCalledTimes(1));
    const payload = apiMock.register.mock.calls[0][0] as { name: string };
    expect(payload.name).toBe("পরীক্ষা শিক্ষার্থী");
    // No whitespace collapsing and no transliteration: the code points are the
    // ones a Bangla keyboard produced (18 code points for
    // "পরীক্ষা শিক্ষার্থী" -- `[...s].length` counts code points, which is what
    // a length validation on the API side would count).
    expect([...payload.name].length).toBe(18);
  });

  it("keeps the typed values on screen when registration fails (G-06)", async () => {
    apiMock.register.mockRejectedValueOnce(
      Object.assign(new Error("taken"), { code: "email_taken" }),
    );

    renderRegister();
    await fillAndSubmit();

    // The error is announced...
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    // ...and nothing the teacher typed is thrown away: retyping a Bangla name
    // after "this email is taken" is the failure mode.
    expect(screen.getByLabelText(t("name"))).toHaveValue("পরীক্ষা শিক্ষার্থী");
    expect(screen.getByLabelText(t("email"))).toHaveValue(
      "qa.verify@example.com",
    );
  });
});
