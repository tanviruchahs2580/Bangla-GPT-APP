import { Capacitor } from "@capacitor/core";
import { currentTheme, onThemeChange } from "./theme";

// E5/native-assets workstream (2026-11-18): the status bar's icon style
// follows the app theme so the system-bar foreground keeps contrast with the
// content background in both light and dark modes. Native-only and strictly
// best-effort: a cosmetic plugin failure must never block or break startup
// (every rejection is swallowed), and nothing here runs in the browser/PWA.
//
// Ownership discipline (matches capacitor.config.ts): this module only sets
// the ICON STYLE. It never calls setOverlaysWebView or setBackgroundColor
// (both are no-ops on API 36) — edge-to-edge geometry stays owned by
// Capacitor 8's SystemBars plugin (insetsHandling: "native") and the CSS
// safe-area rules; a second inset strategy would reintroduce the
// double-inset class of bug.

export async function initNativeSystemUi(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  try {
    const { StatusBar, Style } = await import("@capacitor/status-bar");
    const apply = async () => {
      // Light theme -> dark icons on the light bar; dark theme -> light icons.
      await StatusBar.setStyle({
        style: currentTheme() === "dark" ? Style.Dark : Style.Light,
      });
    };
    await apply();
    onThemeChange(() => {
      void apply().catch(() => {
        /* cosmetic; ignore */
      });
    });
  } catch {
    /* plugin unavailable or rejected — the app runs unchanged without it */
  }
}
