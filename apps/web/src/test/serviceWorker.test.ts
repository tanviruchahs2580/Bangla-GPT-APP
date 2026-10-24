/**
 * Service-worker handler guards (audit 2026-10-23).
 *
 * public/sw.js only runs in a browser SW context, so the source is read from
 * disk and evaluated with its globals injected as parameters. addEventListener
 * records the handlers; the fetch handler is then driven with fake events,
 * testing the shipped file rather than a re-implementation of it.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

// import.meta.url is not a file: URL under the jsdom environment (same note as
// androidManifest.test.ts), so the source is located from the package root.
const SOURCE = readFileSync(join(process.cwd(), "public", "sw.js"), "utf8");

const NAVIGATION = {
  url: "https://app.test/learn",
  method: "GET",
  mode: "navigate",
};

function makeCaches(matchResult?: Response) {
  const put = vi.fn(async () => {});
  const cache = {
    put,
    add: vi.fn(async () => {}),
    keys: vi.fn(async () => [] as string[]),
    delete: vi.fn(async () => true),
  };
  const cachesMock = {
    open: vi.fn(async () => cache),
    match: vi.fn(async () => matchResult),
    keys: vi.fn(async () => [] as string[]),
    delete: vi.fn(async () => true),
  };
  return { cachesMock, put };
}

/** Evaluates the SW with injected globals and returns its recorded handlers. */
function loadSw(
  cachesMock: unknown,
  fetchImpl: unknown,
  selfExtras?: { registration?: unknown; skipWaiting?: () => Promise<void> },
) {
  const handlers: Record<string, (event: unknown) => void> = {};
  const self = {
    addEventListener: (type: string, handler: (event: unknown) => void) => {
      handlers[type] = handler;
    },
    registration: selfExtras?.registration ?? { active: undefined },
    ...(selfExtras?.skipWaiting ? { skipWaiting: selfExtras.skipWaiting } : {}),
  };
  // The globals are parameters here: the Function constructor is the only way
  // to run a worker script in-process with them injected.
  // eslint-disable-next-line @typescript-eslint/no-implied-eval
  const runSw = new Function(
    "self",
    "caches",
    "fetch",
    "Request",
    "Response",
    "URL",
    SOURCE,
  ) as (...args: unknown[]) => void;
  runSw(self, cachesMock, fetchImpl, Request, Response, URL);
  return handlers;
}

/** Fires the recorded fetch handler; returns its respondWith spy. */
function fireFetch(
  handlers: Record<string, (event: unknown) => void>,
  request: unknown,
) {
  const respondWith = vi.fn<(promise: Promise<Response>) => void>();
  handlers.fetch({ request, respondWith });
  return respondWith;
}

describe("public/sw.js update flow (waiting-first, audit M-18)", () => {
  function makeInstallEvent() {
    const waitUntil = vi.fn(async (p: Promise<unknown>) => p);
    return { waitUntil };
  }

  it("FIRST install takes control immediately (skipWaiting)", async () => {
    const { cachesMock } = makeCaches();
    const skipWaiting = vi.fn(async () => {});
    // no active worker on the registration: this is the first install
    const handlers = loadSw(cachesMock, fetch, {
      registration: { active: undefined },
      skipWaiting,
    });
    const install = makeInstallEvent();
    handlers.install(install);
    await install.waitUntil.mock.calls[0][0];
    expect(skipWaiting).toHaveBeenCalledTimes(1);
  });

  it("an UPDATE over a live session does NOT take control (no skipWaiting)", async () => {
    const { cachesMock } = makeCaches();
    const skipWaiting = vi.fn(async () => {});
    // an active worker exists: the new worker is an update, not an install —
    // taking over mid-session would serve a new index.html referencing
    // trimmed hashed chunks; the update waits for the tabs to close instead.
    const handlers = loadSw(cachesMock, fetch, {
      registration: { active: { scriptURL: "/sw.js" } },
      skipWaiting,
    });
    const install = makeInstallEvent();
    handlers.install(install);
    await install.waitUntil.mock.calls[0][0];
    expect(skipWaiting).not.toHaveBeenCalled();
  });
});

describe("public/sw.js navigation handling", () => {
  it("caches a successful navigation as /index.html", async () => {
    const { cachesMock, put } = makeCaches();
    const fetchImpl = vi.fn(
      async () => new Response("<html>ok</html>", { status: 200 }),
    );
    const respondWith = fireFetch(loadSw(cachesMock, fetchImpl), NAVIGATION);

    const res = await respondWith.mock.calls[0][0];
    expect(res.status).toBe(200);
    // The cache write is fire-and-forget, so it lands a microtask later.
    await vi.waitFor(() =>
      expect(put).toHaveBeenCalledWith("/index.html", expect.anything()),
    );
  });

  it("does not cache a 500 response but still returns it", async () => {
    const { cachesMock, put } = makeCaches();
    const fetchImpl = vi.fn(
      async () => new Response("deploy error", { status: 500 }),
    );
    const respondWith = fireFetch(loadSw(cachesMock, fetchImpl), NAVIGATION);

    const res = await respondWith.mock.calls[0][0];
    expect(res.status).toBe(500); // the caller still sees the real error
    await Promise.resolve(); // let a (wrongly) scheduled cache write land
    expect(put).not.toHaveBeenCalled();
  });

  it("returns a 503 offline page when fetch rejects and no shell is cached", async () => {
    const { cachesMock } = makeCaches(); // match → undefined: nothing cached
    const fetchImpl = vi.fn(() => Promise.reject(new Error("offline")));
    const respondWith = fireFetch(loadSw(cachesMock, fetchImpl), NAVIGATION);

    const res = await respondWith.mock.calls[0][0];
    expect(res).toBeDefined(); // undefined here would reject the navigation
    expect(res.status).toBe(503);
  });

  it("returns the cached shell when fetch rejects and one exists", async () => {
    const { cachesMock } = makeCaches(
      new Response("<html>shell</html>", { status: 200 }),
    );
    const fetchImpl = vi.fn(() => Promise.reject(new Error("offline")));
    const respondWith = fireFetch(loadSw(cachesMock, fetchImpl), NAVIGATION);

    const res = await respondWith.mock.calls[0][0];
    expect(await res.text()).toBe("<html>shell</html>");
  });

  it("never intercepts /api/ requests", () => {
    const { cachesMock } = makeCaches();
    const fetchImpl = vi.fn();
    const respondWith = fireFetch(loadSw(cachesMock, fetchImpl), {
      url: "https://app.test/api/health",
      method: "GET",
      mode: "cors",
    });

    expect(respondWith).not.toHaveBeenCalled();
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
