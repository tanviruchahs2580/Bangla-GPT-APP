/**
 * `lib/safeHref` — the trust rule for server-supplied links.
 *
 * FE-FIX: SearchBox navigated straight to `hit.href` from an API response while
 * NotificationBell had always validated its `link` against an in-app
 * allowlist. One rule, one implementation, tested here so both surfaces (and
 * the next one) inherit it.
 */
import { describe, expect, it } from "vitest";
import { uiPathOf, UI_PREFIXES } from "../lib/safeHref";

describe("uiPathOf", () => {
  it("accepts the in-app route prefixes", () => {
    expect(uiPathOf("/student/learn/science/Kosh?class=6")).toBe(
      "/student/learn/science/Kosh?class=6",
    );
    expect(uiPathOf("/parent")).toBe("/parent");
    expect(uiPathOf("/teacher/create?kind=worksheet")).toBe(
      "/teacher/create?kind=worksheet",
    );
    for (const prefix of UI_PREFIXES) {
      expect(uiPathOf(prefix)).toBe(prefix);
    }
  });

  it("rejects anything that is not an in-app route", () => {
    // Absolute and protocol-relative URLs: an open redirect inside an
    // authenticated session.
    expect(uiPathOf("https://evil.example/steal")).toBeNull();
    expect(uiPathOf("//evil.example/steal")).toBeNull();
    expect(uiPathOf("javascript:alert(1)")).toBeNull();
    expect(uiPathOf("data:text/html,<script>")).toBeNull();
    // A prefix that is not a path boundary: "/studentfoo" is not the student
    // area, and the router has no such route.
    expect(uiPathOf("/studentfoo")).toBeNull();
    expect(uiPathOf("/administration")).toBeNull();
    expect(uiPathOf("/")).toBeNull();
    expect(uiPathOf(null)).toBeNull();
    expect(uiPathOf(undefined)).toBeNull();
  });

  it("tolerates surrounding whitespace in the server value", () => {
    expect(uiPathOf("  /student/quiz  ")).toBe("/student/quiz");
  });
});
