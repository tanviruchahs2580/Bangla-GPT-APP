/* Bangla GPT Tutor service worker.
 * Strategy:
 *  - App shell + static assets: cache-first with background refresh.
 *  - Navigations: network-first, offline fallback page.
 *  - API calls: never cached.
 */
// Bumped whenever a shell file's content changes: clients holding the old
// cache keep the old offline.html/offline-retry.js until a fresh cache exists
// (v4: bilingual offline page, external retry handler, update message).
const CACHE = "bgpt-v4";
const MAX_RUNTIME_ENTRIES = 50; // hashed build assets rotate; cap the cache
// Offline navigation fallback. Chrome's installability check requires the
// service worker to answer an OFFLINE navigation with HTTP 200 — the old
// inline 503 page silently revoked the browser's install prompt (audit
// waves-2-4 UAT). Always 200 from here on.
const OFFLINE_URL = "/offline.html";
const SHELL = [
  "/",
  "/index.html",
  "/offline.html",
  // The fallback page's retry/auto-reload handler is an external script (the
  // CSP forbids inline ones), so it must be in the cache too — otherwise the
  // button is dead precisely when offline.html is served from it.
  "/offline-retry.js",
  "/icon.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/manifest.webmanifest",
];

const OFFLINE_FALLBACK_HTML =
  '<!doctype html><html lang="bn"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">' +
  "<title>অফলাইন — বাংলা GPT টিউটর</title></head><body>" +
  "<h1>আপনি এখন অফলাইনে আছেন</h1>" +
  "<p>সংযোগ ফিরলে অ্যাপটি নিজেই লোড হবে।</p></body></html>";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      // One missing shell URL must not abort the whole install (addAll is
      // all-or-nothing): a stale icon path would leave the app with no SW.
      .then((cache) =>
        Promise.all(SHELL.map((url) => cache.add(url).catch(() => {}))),
      )
      .then(() => {
        // Waiting-first updates (audit M-18): skipWaiting is for FIRST
        // installs only (nothing is controlled yet, so taking over is free
        // and first-load offline support works). For an UPDATE over a live
        // session, taking control immediately serves a new index.html that
        // references hashed chunks the old page never loaded — and with
        // MAX_RUNTIME_ENTRIES trimming, chunks the cache no longer holds:
        // a broken page until a manual reload. An updated worker now waits
        // until every old tab has closed (browser default) instead.
        // `active` is null on a first install and `typeof null === 'object'`,
        // so the old shape (`typeof ... === 'object'`) was ALWAYS true and
        // skipWaiting never ran: the behaviour this comment describes was
        // unreachable. Ask the question directly.
        const hadController = self.registration?.active != null;
        if (!hadController && self.skipWaiting) return self.skipWaiting();
        return undefined;
      }),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)),
        ),
      )
      .then(trimRuntimeCache)
      .then(() => self.clients.claim()),
  );
});

// Old hashed assets stay cached forever unless pruned; keep the newest N.
async function trimRuntimeCache() {
  const cache = await caches.open(CACHE);
  const keys = await cache.keys();
  const runtime = keys.filter(
    (req) => !SHELL.includes(new URL(req.url).pathname),
  );
  const excess = runtime.slice(
    0,
    Math.max(0, runtime.length - MAX_RUNTIME_ENTRIES),
  );
  await Promise.all(excess.map((req) => cache.delete(req)));
}

// PWA-02: an update over a live session waits (see the install handler) until
// the page asks for it. The update banner postMessages SKIP_WAITING once the
// student accepts, and the page reloads on controllerchange — so the new shell
// and its hashed chunks arrive together instead of mid-session.
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING" && self.skipWaiting) {
    self.skipWaiting();
  }
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;
  if (url.pathname.startsWith("/api/")) return; // API: always live

  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          // Only a real same-origin page may replace the shell. A deploy-time
          // 500/error page (or an opaque cross-origin response) written over
          // /index.html would be served by every offline navigation until the
          // cache version is bumped.
          if (res.ok && (res.type === "basic" || res.type === "default")) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put("/index.html", copy));
          }
          return res;
        })
        .catch(() =>
          // Order: the real app shell first (it carries the in-app offline
          // banner and full UI), then the dedicated offline page, then a
          // guaranteed 200 inline document — Chrome counts an installation
          // as broken the moment an offline navigation answers 5xx.
          caches.match("/index.html").then(
            (hit) =>
              hit ||
              caches.match(OFFLINE_URL).then(
                (offline) =>
                  offline ||
                  new Response(OFFLINE_FALLBACK_HTML, {
                    status: 200,
                    headers: { "Content-Type": "text/html; charset=utf-8" },
                  }),
              ),
          ),
        ),
    );
    return;
  }

  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(event.request).then((hit) => {
        const fetched = fetch(event.request)
          .then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(event.request, copy));
            }
            return res;
          })
          .catch(() => hit);
        return hit || fetched;
      }),
    );
  }
});
