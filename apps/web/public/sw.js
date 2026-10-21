/* Bangla GPT Tutor service worker.
 * Strategy:
 *  - App shell + static assets: cache-first with background refresh.
 *  - Navigations: network-first, offline fallback page.
 *  - API calls: never cached.
 */
const CACHE = 'bgpt-v2';
const MAX_RUNTIME_ENTRIES = 50; // hashed build assets rotate; cap the cache
const SHELL = [
  '/',
  '/index.html',
  '/icon.svg',
  '/icon-192.png',
  '/icon-512.png',
  '/manifest.webmanifest',
];

/**
 * Cache the hashed bundle the served index.html references (AUD-G-17).
 *
 * `SHELL` holds the HTML, but the app is a JS bundle: caching index.html
 * alone produced an offline "shell" that boots no React and paints an empty
 * page, so a device that went offline before its *second* navigation had
 * nothing usable. The asset URLs are content-hashed and only knowable from
 * the HTML, so they are read out of it and cached explicitly — once at
 * install, and again after every successful navigation (a deploy changes the
 * hashes).
 */
async function warmShellAssets() {
  try {
    const cache = await caches.open(CACHE);
    const index = await cache.match('/index.html');
    if (!index) return;
    const html = await index.text();
    const urls = new Set();
    for (const match of html.matchAll(/["'](\/assets\/[^"']+\.(?:js|css|woff2?))["']/g)) {
      urls.add(match[1]);
    }
    // Preload hints repeat the same URLs; the Set de-duplicates them. A
    // failure here must not fail the install: an offline shell without every
    // font is still an offline shell.
    await Promise.all([...urls].map((url) => cache.add(url).catch(() => undefined)));
  } catch {
    /* best effort */
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(warmShellAssets)
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
          const copy = res.clone();
          caches
            .open(CACHE)
            .then((c) => c.put('/index.html', copy))
            // A deploy changes the asset hashes, so re-warm from the HTML the
            // browser just received rather than trusting last build's list.
            .then(warmShellAssets);
          return res;
        })
        .catch(() => caches.match('/index.html'))
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
