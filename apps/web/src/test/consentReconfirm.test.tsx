/**
 * FE-FIX-019: the consent re-confirmation gate in the web UI.
 *
 * BE-FIX-004 refuses tutor generation and the student's durable writes with a
 * coded 403 whose message names POST /students/{id}/consent/reconfirm, but no
 * web surface called either consent endpoint — the refusal rendered as the
 * generic sentence and the way out did not exist in the product (a
 * CSV-imported class could never submit a quiz again).
 *
 * These cases pin the three halves of the fix: the honest notice renders off
 * the server's own flag, the accept write carries `accepted: true`, and the
 * coded 403 surfaces the same notice + action on the two wired surfaces
 * (quiz, tutor) instead of "কিছু ভুল হয়েছে".
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { useState, type ReactElement } from "react";
import AITutorPage from "../pages/student/AITutorPage";
import QuizPage from "../pages/student/QuizPage";
import { ConsentReconfirmNotice } from "../components/ConsentReconfirmNotice";
import { friendlyError, isConsentReconfirmationRequired } from "../errors";
import { t } from "../i18n";
import type { ConsentStatusOut } from "../types";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  createNote: vi.fn(),
}));

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

const me = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "S",
  class_level: 6,
};

const NEEDS: ConsentStatusOut = {
  student_id: 7,
  current_version: "2026-09-v2",
  accepted_version: "2026-01-v1",
  accepted_at: "2026-01-10T00:00:00Z",
  needs_reconfirm: true,
};
const CURRENT: ConsentStatusOut = {
  ...NEEDS,
  accepted_version: "2026-09-v2",
  needs_reconfirm: false,
};

/** The ApiError api() hands a caller for the gate's coded 403. */
function consent403(): Error & {
  status: number;
  code: string;
  rawDetail: unknown;
} {
  const err = new Error("consent_reconfirmation_required") as Error & {
    status: number;
    code: string;
    rawDetail: unknown;
  };
  err.status = 403;
  err.code = "consent_reconfirmation_required";
  err.rawDetail = {
    code: "consent_reconfirmation_required",
    message:
      "Guardian consent on record is not the current version. Re-confirm at POST /students/7/consent/reconfirm",
    student_id: 7,
    required_version: "2026-09-v2",
  };
  return err;
}

function renderPage(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The consent read the notice performs, routed inside the page-level mocks. */
const consentGet = (status: ConsentStatusOut) => (path: string) =>
  path === "/students/7/consent"
    ? Promise.resolve(status)
    : Promise.resolve(null);

/** A caller's shape: the parent owns the block, the notice reports back. */
function NoticeHarness({ onReconfirmed }: { onReconfirmed?: () => void }) {
  const [blocked, setBlocked] = useState(true);
  return (
    <ConsentReconfirmNotice
      studentId={7}
      blocked={blocked}
      onReconfirmed={() => {
        setBlocked(false);
        onReconfirmed?.();
      }}
    />
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
});

describe("ConsentReconfirmNotice", () => {
  it("renders the notice and the action when the server says a re-confirm is due", async () => {
    apiMock.get.mockImplementation(consentGet(NEEDS));
    renderPage(<ConsentReconfirmNotice studentId={7} />);

    expect(
      await screen.findByTestId("consent-reconfirm-notice"),
    ).toBeInTheDocument();
    expect(screen.getByText(t("consentReconfirmTitle"))).toBeInTheDocument();
    expect(screen.getByText(t("consentReconfirmBody"))).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: t("consentReconfirmAction") }),
    ).toBeEnabled();
  });

  it("renders nothing while consent is current", async () => {
    apiMock.get.mockImplementation(consentGet(CURRENT));
    renderPage(<ConsentReconfirmNotice studentId={7} />);

    await waitFor(() =>
      expect(apiMock.get).toHaveBeenCalledWith("/students/7/consent"),
    );
    expect(screen.queryByTestId("consent-reconfirm-notice")).toBeNull();
  });

  it("accepts with accepted: true and clears the notice in place", async () => {
    const user = userEvent.setup();
    // The invalidated read answers "current" after the accept write.
    apiMock.get
      .mockImplementationOnce(consentGet(NEEDS))
      .mockImplementation(consentGet(CURRENT));
    apiMock.post.mockResolvedValue(CURRENT);
    const onReconfirmed = vi.fn();
    renderPage(<NoticeHarness onReconfirmed={onReconfirmed} />);

    await user.click(
      await screen.findByRole("button", { name: t("consentReconfirmAction") }),
    );
    expect(apiMock.post).toHaveBeenCalledWith("/students/7/consent/reconfirm", {
      accepted: true,
    });
    // No reload: the refetched status hides the notice and the caller is told
    // its block is gone so the gated action can be retried at once.
    await waitFor(() =>
      expect(screen.queryByTestId("consent-reconfirm-notice")).toBeNull(),
    );
    expect(onReconfirmed).toHaveBeenCalled();
  });
});

describe("the gate's coded 403", () => {
  it("maps to localized copy and is recognized as the consent gate", () => {
    expect(
      friendlyError({
        detail: {
          code: "consent_reconfirmation_required",
          message: "Guardian consent on record is not the current version.",
        },
      }).text,
    ).toBe(t("errConsentReconfirmRequired"));
    expect(isConsentReconfirmationRequired(consent403())).toBe(true);
  });
});

describe("QuizPage under the gate", () => {
  const QUIZ_STARTED = {
    attempt_id: 1,
    questions: [
      { id: 1, question_text: "প্রশ্ন", options: ["ক", "খ", "গ", "ঘ"] },
    ],
  };

  it("answers the quiz-start 403 with the notice and action, then works after accept", async () => {
    const user = userEvent.setup();
    // The read is CURRENT on purpose: the 403 is what must surface the notice,
    // not a flag the page happened to fetch.
    apiMock.get.mockImplementation(consentGet(CURRENT));
    let accepted = false;
    apiMock.post.mockImplementation((path: string) => {
      if (path === "/students/7/consent/reconfirm") {
        accepted = true;
        return Promise.resolve(CURRENT);
      }
      if (path === "/quizzes") {
        return accepted
          ? Promise.resolve(QUIZ_STARTED)
          : Promise.reject(consent403());
      }
      return Promise.resolve(null);
    });
    renderPage(<QuizPage />);

    await user.click(
      await screen.findByRole("button", { name: t("startQuiz") }),
    );

    expect(
      await screen.findByTestId("consent-reconfirm-notice"),
    ).toBeInTheDocument();
    expect(screen.queryByText(t("errorGeneric"))).not.toBeInTheDocument();

    // The way out works in place: accept, the notice clears, the same tap
    // starts the quiz — no reload.
    await user.click(
      screen.getByRole("button", { name: t("consentReconfirmAction") }),
    );
    expect(apiMock.post).toHaveBeenCalledWith("/students/7/consent/reconfirm", {
      accepted: true,
    });
    await waitFor(() =>
      expect(screen.queryByTestId("consent-reconfirm-notice")).toBeNull(),
    );
    await user.click(screen.getByRole("button", { name: t("startQuiz") }));
    expect(await screen.findByText("প্রশ্ন")).toBeInTheDocument();
  });
});

describe("AITutorPage under the gate", () => {
  it("shows the re-confirm notice on the tutor surface", async () => {
    apiMock.get.mockImplementation(consentGet(NEEDS));
    renderPage(<AITutorPage />);

    expect(
      await screen.findByTestId("consent-reconfirm-notice"),
    ).toBeInTheDocument();
    expect(screen.getByText(t("consentReconfirmTitle"))).toBeInTheDocument();
  });

  it("answers the tutor turn 403 with the notice instead of the generic sentence", async () => {
    apiMock.get.mockImplementation(consentGet(CURRENT));
    apiMock.post.mockRejectedValue(consent403());
    renderPage(<AITutorPage />);

    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });
    fireEvent.change(box, { target: { value: "kosh ki?" } });
    fireEvent.keyDown(box, { key: "Enter" });

    expect(
      await screen.findByTestId("consent-reconfirm-notice"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: t("consentReconfirmAction") }),
    ).toBeInTheDocument();
    expect(screen.queryByText(t("errorGeneric"))).not.toBeInTheDocument();
    expect(screen.queryByText(t("newChatFailed"))).not.toBeInTheDocument();
  });
});
