/**
 * AUD-HI-07 / I-12: client telemetry is consent-gated.
 *
 * The failure this pins: `main.tsx` used to call `Sentry.init` whenever a DSN
 * was configured, with no consent, no scrubbing and no release tag -- in a
 * product used by minors. These tests drive the real module with a mocked
 * SDK: consent OFF means nothing initialises; consent ON initialises exactly
 * once, with release tagging and a `beforeSend` that strips user, cookies,
 * headers and the URL query string.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { init, close, captureMessage } = vi.hoisted(() => ({
  init: vi.fn(),
  close: vi.fn(async () => true),
  captureMessage: vi.fn(),
}));

vi.mock("@sentry/react", () => ({ init, close, captureMessage }));

const TELEMETRY_KEY = "bgpt.telemetry.consent";

async function loadModule() {
  vi.resetModules();
  return await import("../lib/telemetry");
}

beforeEach(() => {
  localStorage.clear();
  init.mockClear();
  close.mockClear();
  captureMessage.mockClear();
  vi.stubEnv("VITE_SENTRY_DSN", "https://public@example.invalid/1");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("consent gate", () => {
  it("defaults to OFF and never initialises without an explicit opt-in", async () => {
    const telemetry = await loadModule();
    expect(telemetry.telemetryConsent()).toBe(false);
    telemetry.initTelemetry();
    expect(init).not.toHaveBeenCalled();
  });

  it("initialises exactly once when consent is 1 and a DSN is set", async () => {
    localStorage.setItem(TELEMETRY_KEY, "1");
    const telemetry = await loadModule();
    telemetry.initTelemetry();
    telemetry.initTelemetry();
    expect(init).toHaveBeenCalledTimes(1);
    const options = init.mock.calls[0][0] as Record<string, unknown>;
    expect(options.dsn).toBe("https://public@example.invalid/1");
    expect(options.sendDefaultPii).toBe(false);
    expect(options.tracesSampleRate).toBe(0.05);
    expect(options.beforeSend).toBeTypeOf("function");
  });

  it("carries release tagging when the build provides it", async () => {
    localStorage.setItem(TELEMETRY_KEY, "1");
    vi.stubEnv("VITE_RELEASE", "v1.2.3");
    const telemetry = await loadModule();
    telemetry.initTelemetry();
    const options = init.mock.calls[0][0] as Record<string, unknown>;
    expect(options.release).toBe("v1.2.3");
  });

  it("beforeSend strips user, cookies, headers and the query string", async () => {
    localStorage.setItem(TELEMETRY_KEY, "1");
    const telemetry = await loadModule();
    telemetry.initTelemetry();
    const options = init.mock.calls[0][0] as {
      beforeSend: (event: Record<string, unknown>) => Record<string, unknown>;
    };
    const event = {
      user: { id: "42", email: "student@example.com" },
      request: {
        url: "https://app.example/student/me?token=secret",
        cookies: { session: "abc" },
        headers: { authorization: "Bearer x" },
        data: { message: "kept out" },
      },
      breadcrumbs: [
        { data: { url: "https://app.example/chat?q=private%20question" } },
      ],
    };
    const scrubbed = options.beforeSend(event) as {
      user?: unknown;
      request: {
        url?: string;
        cookies?: unknown;
        headers?: unknown;
        data?: unknown;
      };
      breadcrumbs: { data: { url?: string } }[];
    };
    expect(scrubbed.user).toBeUndefined();
    expect(scrubbed.request.cookies).toBeUndefined();
    expect(scrubbed.request.headers).toBeUndefined();
    expect(scrubbed.request.data).toBeUndefined();
    expect(scrubbed.request.url).toBe("https://app.example/student/me");
    expect(scrubbed.breadcrumbs[0].data.url).toBe("https://app.example/chat");
  });

  it("applyTelemetryConsent(false) closes a started client and re-consent restarts", async () => {
    localStorage.setItem(TELEMETRY_KEY, "1");
    const telemetry = await loadModule();
    telemetry.applyTelemetryConsent(true);
    expect(init).toHaveBeenCalledTimes(1);
    telemetry.applyTelemetryConsent(false);
    expect(close).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(TELEMETRY_KEY)).toBe("0");
    telemetry.applyTelemetryConsent(true);
    expect(init).toHaveBeenCalledTimes(2);
  });
});
