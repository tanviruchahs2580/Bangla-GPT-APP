import { describe, expect, it } from "vitest";
import config from "../../capacitor.config";

// The native wrapper reads this file at `npx cap sync`/build time, so the
// settings that keep the Android shell usable are pinned here: a regression
// would resurface as the status bar drawing over the app header on Android
// 15's enforced edge-to-edge (user report 2026-11-17).
describe("capacitor.config.ts", () => {
  it("keeps the production API contract (no cleartext fallback)", () => {
    expect(config.appId).toBe("app.banglagpt.tutor");
    expect(config.android?.allowMixedContent).toBe(false);
  });

  it("insets the WebView below the Android system bars (edge-to-edge)", () => {
    // 'auto': apply margins only where edge-to-edge is enforced, so the
    // header is never overlaid by the status bar and the browser/PWA
    // surfaces (where env() insets are handled in CSS) are unaffected.
    expect(config.android?.adjustMarginsForEdgeToEdge).toBe("auto");
  });
});
