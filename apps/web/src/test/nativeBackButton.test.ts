import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import {
  isDirty,
  markDirty,
  pushOverlay,
  registerBackButton,
  resetRoutes,
  resolveBackAction,
  trackRoute,
} from "../lib/nativeBackButton";

// E6 (mobile audit P1-4): the Android hardware back button had no handling —
// a back press on the root screen discarded an in-progress quiz or a
// streaming tutor answer with no confirmation. The registry semantics are
// unit-tested here; the listener itself is native-only (@capacitor/app is
// inert in the browser/PWA), so device behaviour ships via the CI APK.
//
// vc206 (2026-11-18): the priority ORDER itself is now the contract —
// keyboard → topmost overlay → dirty confirm → in-app route stack → exit —
// and resolveBackAction() makes that order unit-testable without a bridge.
describe("dirty-state registry", () => {
  it("tracks pages that declare resumable state", () => {
    expect(isDirty()).toBe(false);
    const un = markDirty("quiz");
    expect(isDirty()).toBe(true);
    un();
    expect(isDirty()).toBe(false);
  });

  it("unsubscribe is idempotent and keys are independent", () => {
    const a = markDirty("quiz");
    const b = markDirty("tutor");
    a();
    a();
    expect(isDirty()).toBe(true);
    b();
    expect(isDirty()).toBe(false);
  });
});

describe("registerBackButton", () => {
  it("is a no-op outside a native platform", async () => {
    // jsdom: Capacitor.isNativePlatform() is false, so the module must not
    // even import @capacitor/app — the returned cleanup is a plain noop.
    const un = await registerBackButton(() => {});
    expect(typeof un).toBe("function");
    expect(() => un()).not.toThrow();
  });
});

describe("vc206 back priority (resolveBackAction)", () => {
  let cleanups: Array<() => void>;

  beforeEach(() => {
    cleanups = [];
    resetRoutes();
    (document.activeElement as HTMLElement | null)?.blur?.();
  });

  const track = (...fns: Array<() => void>) => cleanups.push(...fns);

  it("exits only at the true root: clean, no overlay, no in-app history", () => {
    expect(resolveBackAction()).toBe("exit");
    trackRoute("/student", "PUSH"); // cold start / deep link seeds the stack
    expect(resolveBackAction()).toBe("exit");
  });

  it("walks the in-app route stack before ever exiting", () => {
    trackRoute("/student", "PUSH");
    trackRoute("/student/tutor", "PUSH");
    expect(resolveBackAction()).toBe("back");
    trackRoute("/student", "POP"); // browser/router back
    expect(resolveBackAction()).toBe("exit");
  });

  it("REPLACE rewrites the top instead of growing the stack", () => {
    trackRoute("/login", "PUSH");
    trackRoute("/", "REPLACE");
    trackRoute("/student/quiz", "PUSH");
    trackRoute("/", "REPLACE"); // auth redirect style replace
    expect(resolveBackAction()).toBe("back");
  });

  it("does not grow the stack when PUSH lands on the current path", () => {
    trackRoute("/student", "PUSH");
    trackRoute("/student", "PUSH");
    trackRoute("/student", "PUSH");
    expect(resolveBackAction()).toBe("exit");
  });

  it("blurs a focused editable first (system keyboard behaviour)", () => {
    trackRoute("/", "PUSH");
    trackRoute("/student/tutor", "PUSH");
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    expect(resolveBackAction()).toBe("keyboard");
    input.blur();
    expect(resolveBackAction()).toBe("back");
    input.remove();
  });

  // jsdom cannot focus contenteditable hosts (isFocusable omits them), so
  // the module's `el.isContentEditable` branch has no jsdom test; the input
  // and textarea branches below cover the editable surfaces the app ships.
  it("blurs a focused textarea first (system keyboard behaviour)", () => {
    trackRoute("/", "PUSH");
    trackRoute("/student/tutor", "PUSH");
    const input = document.createElement("textarea");
    document.body.appendChild(input);
    input.focus();
    expect(resolveBackAction()).toBe("keyboard");
    input.blur();
    expect(resolveBackAction()).toBe("back");
    input.remove();
  });

  it("dismisses the topmost overlay before any navigation", () => {
    trackRoute("/", "PUSH");
    trackRoute("/student/quiz", "PUSH");
    const calls: string[] = [];
    track(pushOverlay(() => calls.push("bottom"))); // cleanups[0]
    track(pushOverlay(() => calls.push("top"))); // cleanups[1]
    expect(resolveBackAction()).toBe("overlay");
    cleanups[1](); // unregister the topmost
    expect(resolveBackAction()).toBe("overlay"); // bottom still open
    cleanups[0]();
    expect(resolveBackAction()).toBe("back");
    expect(calls).toEqual([]); // registry removal is not dismissal
  });

  it("asks before leaving resumable state (dirty beats in-app back)", () => {
    trackRoute("/", "PUSH");
    trackRoute("/student/quiz", "PUSH");
    track(markDirty("quiz"));
    expect(resolveBackAction()).toBe("confirm");
    cleanups[0](); // leave the registry clean for the next test
  });

  it("full order: keyboard > overlay > dirty > back > exit", () => {
    trackRoute("/", "PUSH");
    trackRoute("/student/tutor", "PUSH");
    track(markDirty("tutor"));
    track(pushOverlay(() => {}));
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    expect(resolveBackAction()).toBe("keyboard");
    input.blur();
    expect(resolveBackAction()).toBe("overlay");
    cleanups[cleanups.length - 1](); // close the overlay
    expect(resolveBackAction()).toBe("confirm");
    cleanups[0](); // clear dirty state
    expect(resolveBackAction()).toBe("back");
    trackRoute("/", "POP"); // POP is recorded with the path landed on
    expect(resolveBackAction()).toBe("exit");
    input.remove();
  });

  it("resetRoutes drops stale pre-logout history on shell remount", () => {
    trackRoute("/", "PUSH");
    trackRoute("/student", "PUSH");
    resetRoutes();
    expect(resolveBackAction()).toBe("exit");
  });
});

describe("wiring", () => {
  const ROOT = resolve(process.cwd());
  it("AppShell registers the handler and renders the exit dialog", () => {
    const shell = readFileSync(resolve(ROOT, "src/AppShell.tsx"), "utf8");
    expect(shell).toContain("registerBackButton");
    expect(shell).toContain("ConfirmDialog");
    expect(shell).toContain('t("backLeave")');
  });

  it("the resumable-state pages declare themselves", () => {
    const quiz = readFileSync(
      resolve(ROOT, "src/pages/student/QuizPage.tsx"),
      "utf8",
    );
    const tutor = readFileSync(
      resolve(ROOT, "src/pages/student/AITutorPage.tsx"),
      "utf8",
    );
    expect(quiz).toContain('markDirty("quiz")');
    expect(tutor).toContain('markDirty("tutor")');
  });

  it("the exit-dialog copy exists in bn and en", () => {
    const i18n = readFileSync(resolve(ROOT, "src/i18n.ts"), "utf8");
    for (const key of ["backTitle", "backBody", "backLeave", "backStay"]) {
      expect(i18n.match(new RegExp(`${key}:`, "g"))?.length).toBe(2);
    }
  });
});
