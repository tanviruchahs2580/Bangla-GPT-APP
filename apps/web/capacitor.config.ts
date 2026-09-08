import type { CapacitorConfig } from '@capacitor/cli';

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
  appId: 'app.banglagpt.tutor',
  appName: 'Bangla GPT Tutor',
  webDir: 'dist',
  backgroundColor: '#f4f6fd',
  android: {
    // Production API is TLS-only; no cleartext fallback in the WebView.
    allowMixedContent: false,
  },
};

export default config;
