import * as Sentry from "@sentry/react";

/**
 * Client-side telemetry, consent-gated (AUD-HI-07 / I-12).
 *
 * Nothing is sent unless the user (or their guardian) turned telemetry on in
 * the app; the flag lives in localStorage so the decision survives reloads and
 * is readable before any React tree exists. Default is OFF: an unset flag, a
 * blocked storage API (private mode) or a JSON parse failure all mean "no
 * telemetry", never "yes".
 *
 * What a consenting session sends: error events and four web-vitals
 * aggregates. What it never sends: user ids, emails, request bodies, cookies,
 * header values or URL query strings (a search box is free text).
 */
export const TELEMETRY_CONSENT_KEY = "bgpt.telemetry.consent";

export function telemetryConsent(): boolean {
  try {
    return localStorage.getItem(TELEMETRY_CONSENT_KEY) === "1";
  } catch {
    return false;
  }
}

export function setTelemetryConsent(on: boolean): boolean {
  try {
    localStorage.setItem(TELEMETRY_CONSENT_KEY, on ? "1" : "0");
  } catch {
    return telemetryConsent();
  }
  return on;
}

let started = false;

/** Start error reporting + RUM. Idempotent; a no-op without DSN or consent. */
export function initTelemetry(): void {
  if (started || !telemetryConsent()) return;
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;
  started = true;

  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    // Release tagging: set VITE_RELEASE in the web build (docker build arg /
    // CI env). Without it the tag is simply absent, never fabricated.
    release: import.meta.env.VITE_RELEASE,
    // Error events are the point; performance traces are sampled hard because
    // the users are on low-end devices and shared connections.
    tracesSampleRate: 0.05,
    // No automatic PII: no IP, no user id, no request bodies.
    sendDefaultPii: false,
    beforeSend(event) {
      // Belt and braces around whatever the SDK collected.
      delete event.user;
      if (event.request) {
        delete event.request.cookies;
        delete event.request.headers;
        delete event.request.data;
        if (typeof event.request.url === "string") {
          event.request.url = event.request.url.split("?")[0];
        }
      }
      for (const crumb of event.breadcrumbs ?? []) {
        const data: Record<string, unknown> | undefined = crumb.data;
        if (data && typeof data.url === "string") {
          data.url = data.url.split("?")[0];
        }
      }
      return event;
    },
  });

  void import("web-vitals").then((vitals) => {
    const report = (metric: {
      name: string;
      value: number;
      rating: string;
    }) => {
      // Client-side 10% sampling: vitals are aggregates, and messages are not
      // covered by tracesSampleRate.
      if (Math.random() > 0.1) return;
      Sentry.captureMessage(`web_vital.${metric.name}`, {
        level: "info",
        tags: { rating: metric.rating },
        extra: { value: Math.round(metric.value * 100) / 100 },
      });
    };
    vitals.onCLS(report);
    vitals.onLCP(report);
    vitals.onINP(report);
    vitals.onTTFB(report);
  });
}

/** Called when the user flips the setting: start now, or stop and reset. */
export function applyTelemetryConsent(on: boolean): void {
  setTelemetryConsent(on);
  if (on) {
    initTelemetry();
  } else if (started) {
    void Sentry.close();
    started = false; // a later re-consent starts a fresh client
  }
}
