/* Theme/boot language initializer.
 *
 * S5.6: moved out of the inline <script> in index.html so that the
 * Content-Security-Policy can keep script-src "self" with no inline
 * exception (stock caddy:2-alpine cannot mint per-response nonces).
 * Served as a static file, it runs before first paint, so the persisted
 * theme/language still applies without a flash of the wrong palette.
 */
;(function () {
  try {
    var saved = localStorage.getItem('bgpt_theme')
    var dark = saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
    var lang = localStorage.getItem('bgpt_lang')
    if (lang === 'en' || lang === 'bn') document.documentElement.setAttribute('lang', lang)
  } catch (e) {
    /* private-mode localStorage: keep the markup defaults */
  }
})()
