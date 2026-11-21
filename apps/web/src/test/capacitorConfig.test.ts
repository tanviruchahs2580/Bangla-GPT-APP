import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import config from "../../capacitor.config";

// The native wrapper reads this file at `npx cap sync`/build time, so the
// settings that keep the Android shell usable are pinned here: a regression
// would resurface as the status bar drawing over the app header on Android
// 15+'s enforced edge-to-edge (user report 2026-11-17).
describe("capacitor.config.ts", () => {
  it("keeps the production API contract (no cleartext fallback)", () => {
    expect(config.appId).toBe("app.banglagpt.tutor");
    expect(config.android?.allowMixedContent).toBe(false);
  });

  it("lets Capacitor 8's SystemBars own the Android insets (edge-to-edge)", () => {
    // Capacitor 8 removed android.adjustMarginsForEdgeToEdge; 'native' pads
    // the WebView on Android WebView < 140 and follows viewport-fit=cover on
    // newer WebViews, where the CSS env(safe-area-inset-*) rules take over.
    expect(config.android).not.toHaveProperty("adjustMarginsForEdgeToEdge");
    expect(config.plugins?.SystemBars).toMatchObject({
      insetsHandling: "native",
      initialViewportFitValueHint: "cover",
    });
  });

  it("matches the viewport-fit hint to index.html", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    expect(html).toMatch(/viewport-fit=cover/);
  });
});
