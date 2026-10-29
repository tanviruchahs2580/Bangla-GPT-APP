/* Offline fallback page behaviour (retry button + auto-reload on reconnect).
 *
 * Moved out of the inline <script> in offline.html: both deployments ship
 * `script-src 'self'` with no hash or nonce (apps/web/vercel.json,
 * apps/web/deploy/nginx.conf), so the inline block was blocked by the CSP and
 * the retry button did nothing exactly when the page was needed (PWA-02,
 * FE-07). Same pattern as public/theme-boot.js. Listed in sw.js SHELL, so the
 * file is in the cache when offline.html is served from it.
 */
;(function () {
  var retryBtn = document.getElementById('retry')
  var statusEl = document.getElementById('status')
  if (!retryBtn || !statusEl) return

  function attempt() {
    retryBtn.disabled = true
    statusEl.textContent = 'সংযোগ পরীক্ষা করা হচ্ছে…'
    fetch('/', { method: 'HEAD', cache: 'no-store' })
      .then(function () {
        window.location.reload()
      })
      .catch(function () {
        statusEl.textContent = 'এখনো অফলাইন — সংযোগের অপেক্ষায়…'
        retryBtn.disabled = false
      })
  }

  retryBtn.addEventListener('click', attempt)
  window.addEventListener('online', function () {
    statusEl.textContent = 'সংযোগ ফিরেছে — লোড হচ্ছে…'
    setTimeout(function () {
      window.location.reload()
    }, 400)
  })
})()
