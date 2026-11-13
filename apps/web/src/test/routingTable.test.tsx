/**
 * The routing table and its auth gates, tested against the REAL App.
 *
 * The audit found the entire table untested: 20 routes, RequireAuth's role
 * gating, the role-mismatch redirect, the /welcome-vs-/login branching and
 * the catch-all had no coverage — a regression in role gating (a student
 * reaching /admin, or an authed user stranded on /welcome) would ship
 * green. The shell became importable when App moved out of main.tsx; this
 * is the payoff.
 *
 * Auth is mocked at the context boundary (the same pattern the axe sweep
 * uses) because these cases are about routing decisions, not session
 * mechanics — session behaviour has its own tests (sessionAndStream,
 * round2OutageAndLinks).
 */

import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, queryClient } from "../App";
import * as realAuth from "../AuthContext";
import { setLang, t } from "../i18n";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  const mock: Record<string, unknown> = {};
  for (const key of Object.keys(actual)) {
    if (key === "getToken") mock[key] = vi.fn(() => "test-token");
    else if (key === "get") mock[key] = vi.fn(() => Promise.resolve(null));
    else mock[key] = vi.fn(() => Promise.resolve(null));
  }
  mock.apiBase = "/api";
  return mock;
});

const authState = vi.hoisted(() => ({
  me: null as null | { role: string; name: string; profile_id: number },
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

function renderAt(path: string) {
  window.history.pushState({}, "", path);
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

const STUDENT = {
  role: "student",
  name: "Test Student",
  profile_id: 5,
  user_id: 1,
  email: "s@example.test",
  class_level: 6,
};

beforeEach(() => {
  setLang("bn");
});

afterEach(() => {
  cleanup();
  queryClient.clear();
  authState.me = null;
});

describe("routing table", () => {
  it("sends an anonymous visitor from a guarded route to /login", async () => {
    authState.me = null;
    renderAt("/student");
    // The login form is lazy-loaded; its email field is the anchor.
    expect(
      await screen.findByLabelText(t("email"), {}, { timeout: 5000 }),
    ).toBeTruthy();
    expect(window.location.pathname).toBe("/login");
  });

  it("X-02: a token-missing boot on a deep link preserves the destination in ?next=", async () => {
    // RequireAuth's token-missing navigation used to go to bare /login —
    // the race loser that destroyed the deep link CI's X-02 flake kept
    // hitting. The canonical policy (lib/loginReturn) now serves it.
    authState.me = null;
    renderAt("/student/quiz?attempt=7");
    expect(
      await screen.findByLabelText(t("email"), {}, { timeout: 5000 }),
    ).toBeTruthy();
    expect(window.location.pathname).toBe("/login");
    expect(window.location.search).toBe(
      `?next=${encodeURIComponent("/student/quiz?attempt=7")}`,
    );
  });

  it("X-02: a session-refused boot (me === null with a token) also preserves the destination", async () => {
    // getToken() returns a token (module mock above) but the profile is
    // null: RequireAuth's second /login navigation. It must carry ?next= too.
    authState.me = null;
    renderAt("/student/me?tab=history");
    expect(
      await screen.findByLabelText(t("email"), {}, { timeout: 5000 }),
    ).toBeTruthy();
    expect(window.location.pathname).toBe("/login");
    expect(window.location.search).toBe(
      `?next=${encodeURIComponent("/student/me?tab=history")}`,
    );
  });

  it("X-02: a deep link survives the full round trip — /login?next= returns to it after re-login", async () => {
    // The consumer half: landing on /login?next=… with a session now sends
    // the user BACK to the preserved destination (previously bare /login
    // producers made this impossible to reach deterministically).
    authState.me = STUDENT;
    renderAt(`/login?next=${encodeURIComponent("/student/quiz?attempt=7")}`);
    await waitFor(() => expect(window.location.pathname).toBe("/student/quiz"));
    expect(window.location.search).toBe("?attempt=7");
  });

  it("shows the welcome page to an anonymous visitor at /", async () => {
    authState.me = null;
    renderAt("/");
    expect(
      await screen.findByText(t("landingHeroTitle"), {}, { timeout: 5000 }),
    ).toBeTruthy();
    expect(window.location.pathname).toBe("/welcome");
  });

  it("moves a signed-in student off /welcome to their home", async () => {
    authState.me = STUDENT;
    renderAt("/welcome");
    await waitFor(() => expect(window.location.pathname).toBe("/student"));
    expect(
      await screen.findByText(t("whatToDo"), {}, { timeout: 5000 }),
    ).toBeTruthy();
  });

  it("refuses a student on /admin by redirecting to their own home", async () => {
    authState.me = STUDENT;
    renderAt("/admin");
    await waitFor(() => expect(window.location.pathname).toBe("/student"));
    expect(realAuth.ROLE_HOME.student).toBe("/student");
  });

  it("renders the 404 page for an unknown path instead of silently redirecting", async () => {
    // F-182: the catch-all used to Navigate to "/", so a mistyped deep link
    // looked like the app ignoring the URL and support had nothing to see.
    authState.me = STUDENT;
    renderAt("/definitely-not-a-route");
    expect(
      await screen.findByText(t("noResults"), {}, { timeout: 5000 }),
    ).toBeTruthy();
    // The address that was not found is on the page, and the way home works.
    expect(screen.getByText("/definitely-not-a-route")).toBeTruthy();
    expect(window.location.pathname).toBe("/definitely-not-a-route");
    const home = screen.getByRole("link", { name: t("brandHome") });
    expect(home.getAttribute("href")).toBe("/student");
  });

  it("serves a maintenance screen at /maintenance (F-165)", async () => {
    // Before this a maintenance window could only surface as per-request error
    // copy on whatever page the user happened to be on. The deployment serves
    // the SPA for this path (vercel.json rewrites everything to index.html;
    // nginx falls back the same way), so the route is the whole product half.
    authState.me = null;
    renderAt("/maintenance");
    expect(
      await screen.findByText(t("apiUnreachableTitle"), {}, { timeout: 5000 }),
    ).toBeTruthy();
    expect(screen.getByText(t("apiUnreachableBody"))).toBeTruthy();
    // Retry acts on the page, and the status page is reachable from it (the
    // public footer carries the same link, so this is a set membership).
    expect(screen.getByRole("button", { name: t("retry") })).toBeTruthy();
    const statusLinks = screen.getAllByRole("link", {
      name: t("statusPage"),
    });
    expect(
      statusLinks.some((link) => link.getAttribute("href") === "/status"),
    ).toBe(true);
  });
});
