/**
 * F-022 (PWA-02, FE-07): both deployments ship `script-src 'self'` with no
 * hash or nonce, so any inline <script> in the offline fallback page is
 * blocked by the browser and the retry button dies exactly when connectivity
 * is gone. The handler now lives in a same-origin file; this locks the
 * invariant (no inline script), the file link and the service-worker cache
 * entry. The Chromium probe under the exact vercel.json CSP (evidence
 * E-FIX-F-022-1) proves the handler actually runs.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const PUBLIC = resolve(process.cwd(), "public");
const html = readFileSync(resolve(PUBLIC, "offline.html"), "utf8");
const sw = readFileSync(resolve(PUBLIC, "sw.js"), "utf8");

describe("offline fallback page under script-src 'self' (F-022)", () => {
  it("ships no inline script", () => {
    const scripts = [...html.matchAll(/<script\b[^>]*>/g)].map((m) => m[0]);
    expect(scripts.length).toBeGreaterThan(0);
    for (const tag of scripts) {
      expect(tag, `inline script would be CSP-blocked: ${tag}`).toMatch(
        /\ssrc="/,
      );
    }
  });

  it("loads the retry/auto-reload handler from a same-origin file", () => {
    expect(html).toContain('<script src="/offline-retry.js"');
    const handler = readFileSync(resolve(PUBLIC, "offline-retry.js"), "utf8");
    expect(handler).toContain("retry");
    expect(handler).toContain("online");
  });

  it("keeps the handler in the service-worker shell cache", () => {
    // offline.html is served from the cache; a handler that is not cached
    // beside it would 404 the moment it is needed.
    expect(sw).toMatch(/"\/offline-retry\.js"/);
  });
});
