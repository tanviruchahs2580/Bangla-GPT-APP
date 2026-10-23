/**
 * I18N: switching language must re-render, never remount.
 *
 * The shipped implementation keyed a wrapper element by a counter, so every
 * language switch REMOUNTED the entire tree: a student mid-quiz lost their
 * in-progress attempt, a streaming tutor answer was aborted, and half-filled
 * forms reset — triggered by a control the UI invites users to press at any
 * time. This test mounts the real ``App`` (the same component ``main.tsx``
 * renders) on the login route, types into a field, switches the language
 * with the public toggle, and asserts BOTH halves of the fix: the copy is
 * re-rendered in the new language AND the typed state survived.
 *
 * A remount would pass the first assertion and fail the second.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, queryClient } from "../App";
import { AuthProvider } from "../AuthContext";
import { getLang, setLang, t } from "../i18n";

// The App tree touches every named export of the api module on mount
// (session probe, queries); stubs resolve to "no data" shapes, matching the
// pattern the axe sweep already established.
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  const mock: Record<string, unknown> = {};
  for (const key of Object.keys(actual)) {
    if (key === "get") mock[key] = vi.fn(() => Promise.resolve(null));
    else if (key === "getToken") mock[key] = vi.fn(() => null);
    else mock[key] = vi.fn(() => Promise.resolve(null));
  }
  mock.apiBase = "/api";
  return mock;
});

function renderApp(path: string) {
  window.history.pushState({}, "", path);
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("language switch preserves page state", () => {
  beforeEach(() => {
    setLang("bn");
    document.documentElement.setAttribute("lang", "bn");
    queryClient.clear();
  });

  afterEach(() => {
    cleanup();
    setLang("bn");
    queryClient.clear();
  });

  it("keeps what the user typed while the copy switches language", async () => {
    renderApp("/login");

    // The login form is lazy-loaded; wait for the real field.
    const email = await screen.findByLabelText(
      t("email"),
      {},
      { timeout: 5000 },
    );
    await userEvent.type(email, "student@example.test");
    expect((email as HTMLInputElement).value).toBe("student@example.test");

    const toggle = screen.getByRole("button", { name: t("language") });
    await userEvent.click(toggle);

    expect(getLang()).toBe("en");
    await waitFor(() => {
      // The copy re-rendered in the new language…
      expect(screen.getByLabelText(t("email"))).toBeTruthy();
    });
    // …and the field kept its value: no remount happened.
    const emailAfter = screen.getByLabelText<HTMLInputElement>(t("email"));
    expect(emailAfter).toBe(email);
    expect(emailAfter.value).toBe("student@example.test");

    // And switching back is equally lossless.
    await userEvent.click(screen.getByRole("button", { name: t("language") }));
    expect(getLang()).toBe("bn");
    expect(screen.getByLabelText<HTMLInputElement>(t("email")).value).toBe(
      "student@example.test",
    );
  });
});
