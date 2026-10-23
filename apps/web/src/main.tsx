import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import * as Sentry from "@sentry/react";
// Sentry — no-op when DSN absent
if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN as string,
    environment: import.meta.env.MODE,
    tracesSampleRate: 0.1,
  });
}
import "./styles.css";
import "@fontsource/noto-sans-bengali/400.css";
import "@fontsource/noto-sans-bengali/700.css";
import "@fontsource/hind-siliguri/400.css";
import "@fontsource/hind-siliguri/600.css";
import { App, queryClient } from "./App";
import { AuthProvider } from "./AuthContext";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import { initInstallPrompt } from "./lib/installPrompt";
import { initLowData } from "./lib/lowData";

// apply the persisted low-data mode before first paint.
initLowData();
initInstallPrompt();
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* Last-resort boundary for errors above the routes (providers, shell);
        per-route recovery lives in RouteErrorBoundary (F-001). */}
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </QueryClientProvider>
    </AppErrorBoundary>
  </React.StrictMode>,
);

// PWA: register the service worker in production builds only — in dev the
// cache-first strategy would serve stale Vite modules and break HMR.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* offline support is best-effort; never block the app on SW errors */
    });
  });
}
