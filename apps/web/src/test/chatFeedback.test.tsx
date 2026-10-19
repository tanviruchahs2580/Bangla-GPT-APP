/** AUD-G-10: copy-the-answer control and the thumbs-down reason prompt. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { t } from "../i18n";
import {
  ANSWER_TEXT,
  askOneQuestion,
  renderTutorPage,
  wireTutorMocks,
} from "./tutorPageMock";

// The hoisted surface must stay per-file: vi.mock factories run before module
// imports, so a shared module crashes this vitest build's worker (measured;
// see the harness docstring).
const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));
const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));
vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

describe("chat answer actions", () => {
  beforeEach(() => {
    wireTutorMocks(apiMock, authMock);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn() },
    });
  });

  /** Spy on the clipboard object the component will actually call.
   *
   * userEvent.setup() installs its own clipboard stub, so a mock defined
   * before setup() is shadowed and never invoked; spying after setup() binds
   * to whichever writeText the component reaches at click time.
   */
  function clipboardSpy() {
    return vi.spyOn(navigator.clipboard, "writeText");
  }

  it("copies an answer to the clipboard and confirms it", async () => {
    const user = userEvent.setup();
    const writeText = clipboardSpy();
    writeText.mockResolvedValue(undefined);
    renderTutorPage();
    const copy = await askOneQuestion(user);

    await user.click(copy);
    expect(writeText).toHaveBeenCalledWith(ANSWER_TEXT);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-announcer")).toHaveTextContent(
        t("copied"),
      ),
    );
  });

  it("says so when the clipboard refuses, instead of failing silently", async () => {
    const user = userEvent.setup();
    clipboardSpy().mockRejectedValue(new Error("denied"));
    renderTutorPage();
    const copy = await askOneQuestion(user);

    await user.click(copy);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-announcer")).toHaveTextContent(
        t("copyFailed"),
      ),
    );
  });

  it("asks for a reason on thumbs-down and posts it as the comment", async () => {
    const user = userEvent.setup();
    renderTutorPage();
    await askOneQuestion(user);

    await user.click(screen.getByRole("button", { name: t("rateDown") }));
    const dialog = await screen.findByRole("dialog");
    await user.type(
      within(dialog).getByLabelText(t("feedbackReasonTitle")),
      "পাঠ্যবইয়ের সাথে মিলছে না",
    );
    await user.click(
      within(dialog).getByRole("button", { name: t("feedbackSend") }),
    );

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/feedback", {
        rating: -1,
        message_id: 2,
        comment: "পাঠ্যবইয়ের সাথে মিলছে না",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("still records the rating when the reader skips the reason", async () => {
    const user = userEvent.setup();
    renderTutorPage();
    await askOneQuestion(user);

    await user.click(screen.getByRole("button", { name: t("rateDown") }));
    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getByRole("button", { name: t("feedbackSkip") }),
    );

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/feedback", {
        rating: -1,
        message_id: 2,
      }),
    );
  });
});
