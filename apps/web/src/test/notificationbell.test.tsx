// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { NotificationBell } from "../components/NotificationBell";
import { setLang, t } from "../i18n";
import type { NotificationList } from "../api";

const apiMock = vi.hoisted(() => ({
  getNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
}));

const LIST: NotificationList = {
  items: [
    {
      id: 2,
      kind: "parent_link",
      // Backend wire codes are snake_case; dict keys are camelCase.
      code: "notif_parent_linked",
      params: { student_id: 124 },
      link: "/student/me",
      read_at: null,
      created_at: "2026-09-08T15:52:00",
    },
    {
      id: 3,
      kind: "assignment",
      code: "notif_quiz_assigned",
      params: { subject: "Physics", chapter: "Motion", count: 5 },
      link: "/student/quiz",
      read_at: null,
      created_at: "2026-09-08T15:53:00",
    },
    {
      id: 4,
      kind: "mystery",
      code: "notif_never_seen_before",
      params: { any: "thing" },
      link: null,
      read_at: "2026-09-08T15:54:00",
      created_at: "2026-09-08T15:54:00",
    },
  ],
  unread_count: 2,
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.setItem("bgpt_lang", "en");
  setLang("en");
  apiMock.getNotifications.mockResolvedValue(LIST);
  apiMock.markNotificationRead.mockResolvedValue({});
});

describe("NotificationBell code mapping", () => {
  it("renders localized copy for snake_case wire codes and falls back safely", async () => {
    // Regression: the bell crashed the whole app when an unknown wire code
    // hit t() with params (undefined.replaceAll inside the translator).
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /notifications/i }),
    );
    await waitFor(() =>
      expect(screen.getByText("Guardian link established")).toBeInTheDocument(),
    );
    // Params are interpolated into the translated template.
    expect(screen.getByText(/Physics.*Motion/)).toBeInTheDocument();
    // Unknown code: raw wire code shown, no crash.
    expect(screen.getByText("notif_never_seen_before")).toBeInTheDocument();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });
});

// FE-FIX-004: a failed notifications read used to be swallowed by an empty
// catch, so the panel said "No notifications yet" — a claim about the
// student's account — and the unread badge disappeared, hiding a quiz the
// teacher had just assigned. The failure is named now, with a retry, and the
// count is withheld rather than reported as zero.
describe("NotificationBell failure state", () => {
  it("names the failure and retries, without claiming there is nothing", async () => {
    apiMock.getNotifications.mockRejectedValue(new Error("503"));
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>,
    );
    const trigger = await screen.findByRole("button", {
      name: new RegExp(t("notifLoadFailed")),
    });
    await userEvent.click(trigger);

    expect(screen.getByText(t("notifLoadFailed"))).toBeInTheDocument();
    expect(screen.queryByText(t("notifEmpty"))).not.toBeInTheDocument();
    // The count is unknown, not zero: the badge says so instead of vanishing.
    expect(screen.getByText("!")).toBeInTheDocument();

    apiMock.getNotifications.mockResolvedValue(LIST);
    await userEvent.click(screen.getByRole("button", { name: t("retry") }));
    await waitFor(() =>
      expect(screen.queryByText(t("notifLoadFailed"))).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Guardian link established")).toBeInTheDocument();
  });
});

// FE-FIX (numerals): the unread count is a quantity, so it renders in the
// language's digits at the t()/formatNumber boundary — including inside the
// trigger's accessible name, which is where a screen-reader student reads it.
describe("NotificationBell numeral policy", () => {
  it("counts in Bangla digits under bn, in the badge and in the name", async () => {
    localStorage.setItem("bgpt_lang", "bn");
    setLang("bn");
    apiMock.getNotifications.mockResolvedValue({ ...LIST, unread_count: 12 });
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>,
    );

    // 12 unread is announced as "৯+" — the badge's cap is the same in both
    // languages, and the digits follow the active one.
    const trigger = await screen.findByRole("button", {
      name: `${t("notifications")}: ৯+`,
    });
    expect(trigger).toBeTruthy();
    expect(screen.getByText("৯+")).toBeInTheDocument();
  });
});
