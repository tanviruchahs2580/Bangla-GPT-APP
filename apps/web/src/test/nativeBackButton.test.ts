import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  isDirty,
  markDirty,
  registerBackButton,
} from "../lib/nativeBackButton";

// E6 (mobile audit P1-4): the Android hardware back button had no handling —
// a back press on the root screen discarded an in-progress quiz or a
// streaming tutor answer with no confirmation. The registry semantics are
// unit-tested here; the listener itself is native-only (@capacitor/app is
// inert in the browser/PWA), so device behaviour ships via the CI APK.
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
