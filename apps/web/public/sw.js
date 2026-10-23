/* Bangla GPT Tutor service worker.
 * Strategy:
 *  - App shell + static assets: cache-first with background refresh.
 *  - Navigations: network-first, offline fallback page.
 *  - API calls: never cached.
 */
const CACHE = 'bgpt-v2';
const MAX_RUNTIME_ENTRIES = 50; // hashed build assets rotate; cap the cache
// Last-resort navigation when the network fails and no shell was ever cached
// (first visit on a broken connection). Mirrors the in-app offline banner.
const OFFLINE_HTML =
  '<!doctype html><html lang="bn"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<title>অফলাইন</title></head><body>' +
  '<h1>অফলাইন — সংযোগ ফিরলে আবার চেষ্টা করুন</h1></body></html>';
const SHELL = [
  '/',
  '/index.html',
  '/icon.svg',
  '/icon-192.png',
  '/icon-512.png',
  '/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      // One missing shell URL must not abort the whole install (addAll is
      // all-or-nothing): a stale icon path would leave the app with no SW.
      .then((cache) => Promise.all(SHELL.map((url) => cache.add(url).catch(() => {}))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(trimRuntimeCache)
      .then(() => self.clients.claim())
  );
});

// Old hashed assets stay cached forever unless pruned; keep the newest N.
async function trimRuntimeCache() {
  const cache = await caches.open(CACHE);
  const keys = await cache.keys();
  const runtime = keys.filter((req) => !SHELL.includes(new URL(req.url).pathname));
  const excess = runtime.slice(0, Math.max(0, runtime.length - MAX_RUNTIME_ENTRIES));
  await Promise.all(excess.map((req) => cache.delete(req)));
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return; // API: always live

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          // Only a real same-origin page may replace the shell. A deploy-time
          // 500/error page (or an opaque cross-origin response) written over
          // /index.html would be served by every offline navigation until the
          // cache version is bumped.
          if (res.ok && (res.type === 'basic' || res.type === 'default')) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put('/index.html', copy));
          }
          return res;
        })
        .catch(() =>
          caches.match('/index.html').then(
            (hit) =>
              hit ||
              // Before the first successful navigation there is no shell to
              // match; respondWith(undefined) would reject the navigation, so
              // answer an explicit 503 offline page instead.
              new Response(OFFLINE_HTML, {
                status: 503,
                headers: { 'Content-Type': 'text/html; charset=utf-8' },
              })
          )
        )
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
      })
    );
  }
});
