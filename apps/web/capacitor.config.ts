import type { CapacitorConfig } from "@capacitor/cli";

/**
 * S5.9 native wrapper config (Android first; iOS later on a Mac).
 *
 * The web bundle stays the single source of truth: build dist first, then
 * `npx cap sync` copies it into the native projects.
 *
 * IMPORTANT for native: the WebView origin is capacitor://localhost, so the
 * relative API base ('/api') cannot reach the backend. Release builds MUST
 * set VITE_API_BASE to the absolute API URL before building, e.g.
 *   VITE_API_BASE=https://api.example.com/api npm run build && npx cap sync
 * and the API CORS must allow the capacitor://localhost / https://localhost
 * origins (see docs/mobile_release.md for the full release procedure).
 */
const config: CapacitorConfig = {
  appId: "app.banglagpt.tutor",
  appName: "Bangla GPT Tutor",
  webDir: "dist",
  backgroundColor: "#f4f6fd",
  android: {
    // Production API is TLS-only; no cleartext fallback in the WebView.
    allowMixedContent: false,
    // Android 15 (targetSdk 35) enforces edge-to-edge: the status bar draws
    // OVER the WebView and covered the app header's upper part (user report
    // 2026-11-17, screenshot). 'auto' lets the bridge inset the WebView below
    // the system bars only where edge-to-edge is enforced, so the header is
    // never overlaid. The stylesheet's env(safe-area-inset-*) rules stay for
    // the browser/PWA surfaces, where Android's WebView reports 0 insets.
    adjustMarginsForEdgeToEdge: "auto",
  },
};

export default config;
