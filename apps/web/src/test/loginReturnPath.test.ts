/**
 * X-02: the canonical return-path policy for every bounce to /login.
 *
 * Three producers used to disagree: AuthContext's 401 bounce carried
 * ?next=, RequireAuth's two bare <Navigate to="/login"> redirects did not —
 * the race loser silently destroyed the user's deep link (CI's X-02 flake).
 * One helper now serves all of them, and these tests pin its contract.
 */
import { describe, expect, it } from "vitest";
import { loginReturnPath, safeNextPath } from "../lib/loginReturn";

function at(path: string): void {
  window.history.pushState({}, "", path);
}

describe("loginReturnPath — producer side (redirect targets)", () => {
  it("carries a deep link as ?next=", () => {
    at("/student/quiz?attempt=7");
    expect(loginReturnPath()).toBe(
      `/login?next=${encodeURIComponent("/student/quiz?attempt=7")}`,
    );
  });

  it("stays plain /login when already heading there", () => {
    at("/login?next=%2Fstudent");
    expect(loginReturnPath()).toBe("/login");
  });

  it("stays plain /login at the root (nothing to preserve)", () => {
    at("/");
    expect(loginReturnPath()).toBe("/login");
  });

  it("preserves the query string of the deep link, not just the pathname", () => {
    at("/student/me?tab=history");
    expect(loginReturnPath()).toBe(
      `/login?next=${encodeURIComponent("/student/me?tab=history")}`,
    );
  });
});

describe("safeNextPath — consumer side (post-login return)", () => {
  it("accepts a same-origin relative path", () => {
    expect(safeNextPath("?next=%2Fstudent%2Fquiz")).toBe("/student/quiz");
  });

  it("preserves an embedded query in the destination", () => {
    expect(
      safeNextPath(`?next=${encodeURIComponent("/student/me?tab=1")}`),
    ).toBe("/student/me?tab=1");
  });

  it.each([
    ["an absolute URL", "?next=https%3A%2F%2Fevil.test"],
    ["a protocol-relative path", "?next=%2F%2Fevil.test"],
    ["a backslash variant", "?next=%2F%5Cevil.test"],
    ["a fragment-only value", "?next=%23evil"],
    ["an empty value", "?next="],
    ["a missing parameter", ""],
  ])("rejects %s", (_label, search) => {
    expect(safeNextPath(search)).toBeNull();
  });
});
