/**
 * WCAG 2.4.1 / 2.4.6 (A11Y-02, A11Y-03; F-003): no route shipped a skip link,
 * and the public and staff layouts (login, register, forgot, privacy, terms,
 * status, parent, admin) shipped no <main> either — a keyboard user re-tabbed
 * the whole topbar plus sidebar on every navigation and a screen-reader user
 * got no main landmark at all.
 *
 * This drives the REAL routing table (same harness as routingTable.test.tsx)
 * and asserts, per route: a skip link is the first focusable element, it
 * points at exactly one <main id="main-content">, and the route never grows a
 * second main landmark. The e2e keyboard/crawl specs assert the same contract
 * in a browser; this is the unit-level guard that runs everywhere.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, queryClient } from "../App";
import { setLang, t } from "../i18n";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  const mock: Record<string, unknown> = {};
  for (const key of Object.keys(actual)) {
    mock[key] = key === "getToken" ? vi.fn(() => "test-token") : vi.fn();
  }
  for (const fn of Object.values(mock)) {
    if (typeof fn === "function" && "mockResolvedValue" in fn) {
      (fn as ReturnType<typeof vi.fn>).mockResolvedValue(null);
    }
  }
  return mock;
});

const authState = vi.hoisted(() => ({
  me: null as null | {
    role: string;
    name: string;
    profile_id: number;
    user_id: number;
    email: string;
    class_level: number;
  },
  loading: false,
  apiUnreachable: false,
  retrySession: () => {},
}));

vi.mock("../AuthContext", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    useAuth: () => authState,
    AuthProvider: ({ children }: { children: ReactNode }) => children,
  };
});

const WHO = (role: string) => ({
  role,
  name: `${role} user`,
  profile_id: 5,
  user_id: 1,
  email: `${role}@example.test`,
  class_level: 6,
});

/** Every route in App.tsx that renders a page (not a redirect). */
const ROUTES: Array<[string, string | null]> = [
  ["/welcome", null],
  ["/login", null],
  ["/register", null],
  ["/forgot", null],
  ["/privacy", null],
  ["/terms", null],
  ["/status", null],
  ["/student", "student"],
  ["/student/me", "student"],
  ["/student/tutor", "student"],
  ["/teacher", "teacher"],
  ["/parent", "parent"],
  ["/admin", "admin"],
];

function renderAt(path: string) {
  window.history.pushState({}, "", path);
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

/** The first element in the document a Tab press reaches. */
function firstFocusable(): Element | null {
  return document.querySelector(
    'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])',
  );
}

beforeEach(() => {
  setLang("bn");
  authState.me = null;
});

afterEach(() => {
  cleanup();
  queryClient.clear();
  authState.me = null;
});

describe("skip link and main landmark (F-003)", () => {
  it.each(ROUTES)("%s", async (path, role) => {
    authState.me = role ? WHO(role) : null;
    const { container } = renderAt(path);

    const main = await waitFor(
      () => {
        const found = container.querySelector("main#main-content");
        expect(found, `no main#main-content on ${path}`).toBeTruthy();
        return found as HTMLElement;
      },
      { timeout: 8000 },
    );

    // Exactly one main landmark: a duplicate is its own axe violation.
    expect(document.querySelectorAll("main")).toHaveLength(1);
    expect(main.tagName).toBe("MAIN");

    // The skip link precedes everything else in the tab order and targets it.
    const first = firstFocusable();
    expect(first, `no focusable element on ${path}`).toBeTruthy();
    expect(first?.classList.contains("skip-link")).toBe(true);
    expect(first?.getAttribute("href")).toBe("#main-content");
    expect(first).toHaveTextContent(t("skipToContent"));
  });

  it("keeps the skip link out of the layout until it is focused", () => {
    // jsdom never loads styles.css, and the link must not sit visibly on top
    // of every page: off-screen until focus, never display:none (it has to
    // stay in the tab order and the accessible tree).
    const css = readFileSync(
      resolve(process.cwd(), "src", "styles.css"),
      "utf8",
    );
    const rule = css.match(/\.skip-link\s*\{[^}]*\}/)?.[0] ?? "";
    expect(rule).toContain("transform: translateY(-200%)");
    expect(rule).not.toContain("display: none");
    expect(css).toMatch(/\.skip-link:focus[^{]*\{[^}]*translateY\(0\)/);
  });
});

/**
 * F-168: the student surface had no h1 at all (the page title was an h2)
 * while the staff pages used h1.page-title, so the document outline depended
 * on the role; structured answers then jumped h2 -> h4. This walks the same
 * routing table and holds every route to one outline: exactly one h1, and no
 * level skipped on the way down.
 */
describe("heading order (F-168)", () => {
  beforeEach(() => {
    setLang("bn");
    authState.me = null;
  });

  afterEach(() => {
    cleanup();
    queryClient.clear();
    authState.me = null;
  });

  it.each(ROUTES)("%s", async (path, role) => {
    authState.me = role ? WHO(role) : null;
    const { container } = renderAt(path);
    await waitFor(
      () => {
        expect(
          container.querySelector("h1, h2, h3, h4, h5, h6"),
          `no heading rendered on ${path}`,
        ).toBeTruthy();
      },
      { timeout: 8000 },
    );

    const headings = [...container.querySelectorAll("h1, h2, h3, h4, h5, h6")];
    const levels = headings.map((h) => Number(h.tagName.slice(1)));
    expect(
      container.querySelectorAll("h1"),
      `expected exactly one h1 on ${path}`,
    ).toHaveLength(1);
    // The page title comes first: a section heading above it would make the
    // outline start in the middle.
    expect(levels[0], `first heading is not the h1 on ${path}`).toBe(1);
    for (let i = 1; i < levels.length; i += 1) {
      expect(
        levels[i] - levels[i - 1],
        `heading level jumps from h${levels[i - 1]} to h${levels[i]} on ${path}: "${headings[i].textContent?.trim()}"`,
      ).toBeLessThanOrEqual(1);
    }
  });
});
