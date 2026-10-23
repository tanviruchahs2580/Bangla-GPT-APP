/**
 * Keyboard contracts the ARIA roles promise.
 *
 * The audit found three widgets announcing rich roles (`radiogroup`, `menu`,
 * `listbox`) while implementing none of the keyboard behaviour those roles
 * guarantee — axe cannot catch this class (it does not test key handling),
 * which is exactly why these tests exist. Each case drives the real
 * component with real key events and asserts the APG contract: single tab
 * stop + arrow traversal for the radio group, focus-move + Escape-restore
 * for the menu, and combobox-style traversal for search.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationBell } from "../components/NotificationBell";
import { SearchBox } from "../components/SearchBox";
import { t } from "../i18n";
import QuizPage from "../pages/student/QuizPage";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  getNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, ...apiMock };
});
vi.mock("../AuthContext", () => authMock);

const me = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "S",
  class_level: 6,
};

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
});

afterEach(() => cleanup());

describe("quiz radiogroup keyboard contract", () => {
  async function startQuiz() {
    apiMock.get.mockResolvedValue({ attempts_graded: 0, avg_score_pct: null });
    apiMock.post.mockResolvedValue({
      attempt_id: 1,
      requested: 1,
      questions: [
        {
          id: "q1",
          question_text: "2+2?",
          options: ["3", "4", "5", "6"],
        },
      ],
    });
    wrap(<QuizPage />);
    const user = userEvent.setup();
    await user.click(screen.getAllByRole("button", { name: /কুইজ শুরু/ })[0]);
    const radios = await screen.findAllByRole("radio");
    expect(radios).toHaveLength(4);
    return { user, radios };
  }

  it("keeps one tab stop and moves selection with the arrow keys", async () => {
    const { user, radios } = await startQuiz();

    // Roving tab stop: only the first option before any choice exists.
    expect(radios.map((r) => r.getAttribute("tabindex"))).toEqual([
      "0",
      "-1",
      "-1",
      "-1",
    ]);

    radios[0].focus();
    await user.keyboard("{ArrowDown}");
    expect(radios[1]).toHaveAttribute("aria-checked", "true");
    expect(document.activeElement).toBe(radios[1]);
    // The tab stop followed the selection.
    expect(radios.map((r) => r.getAttribute("tabindex"))).toEqual([
      "-1",
      "0",
      "-1",
      "-1",
    ]);

    await user.keyboard("{End}");
    expect(radios[3]).toHaveAttribute("aria-checked", "true");

    // Wrap-around at the end, per APG.
    await user.keyboard("{ArrowDown}");
    expect(radios[0]).toHaveAttribute("aria-checked", "true");

    // And backwards wraps to the last option.
    await user.keyboard("{ArrowUp}");
    expect(radios[3]).toHaveAttribute("aria-checked", "true");
  });
});

describe("notification menu keyboard contract", () => {
  const items = [
    {
      id: 1,
      kind: "assignment",
      code: "notif_quiz_assigned",
      params: { count: 3 },
      link: null,
      read_at: null,
      created_at: null,
    },
    {
      id: 2,
      kind: "assignment",
      code: "notif_quiz_assigned",
      params: { count: 1 },
      link: null,
      read_at: "2026-01-01T00:00:00",
      created_at: null,
    },
  ];

  async function openMenu() {
    apiMock.getNotifications.mockResolvedValue({ items, unread_count: 1 });
    const user = userEvent.setup();
    wrap(<NotificationBell />);
    const trigger = screen.getByRole("button", { name: t("notifications") });
    await user.click(trigger);
    const menuItems = await screen.findAllByRole("menuitem");
    expect(menuItems).toHaveLength(2);
    return { user, trigger, menuItems };
  }

  it("moves focus on open and on arrows, Escape closes and restores it", async () => {
    const { user, trigger, menuItems } = await openMenu();

    // Opening moves focus to the first item (APG menu button).
    await waitFor(() => expect(document.activeElement).toBe(menuItems[0]));

    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(menuItems[1]);
    await user.keyboard("{ArrowDown}"); // wraps
    expect(document.activeElement).toBe(menuItems[0]);
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(menuItems[1]);

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryAllByRole("menuitem")).toHaveLength(0),
    );
    // Focus returns to the trigger so the keyboard user is not dropped at
    // the top of the document.
    expect(document.activeElement).toBe(trigger);
  });
});

describe("search combobox keyboard contract", () => {
  it("traverses results with arrows and activates the active option", async () => {
    apiMock.get.mockResolvedValue({
      query: "ko",
      ask_action: false,
      hits: [
        {
          kind: "chapter",
          title: "কোষ",
          href: "/student/learn/science/কোষ",
          subtitle: null,
        },
        {
          kind: "chapter",
          title: "কোষ বিভাজন",
          href: "/student/learn/science/কোষ-বিভাজন",
          subtitle: null,
        },
      ],
    });
    const user = userEvent.setup();
    wrap(<SearchBox />);
    const input = screen.getByRole("combobox");

    await user.type(input, "ko");
    const options = await screen.findAllByRole("option", {}, { timeout: 4000 });
    expect(options).toHaveLength(2);
    expect(input).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{ArrowDown}");
    // aria-activedescendant names the highlighted option while focus stays
    // in the input — the contract the old listbox-only markup broke.
    expect(input.getAttribute("aria-activedescendant")).toBe("search-option-0");
    await user.keyboard("{ArrowDown}");
    expect(input.getAttribute("aria-activedescendant")).toBe("search-option-1");
    expect(options[1]).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryAllByRole("option")).toHaveLength(0),
    );
    expect(input).toHaveAttribute("aria-expanded", "false");
  });
});
