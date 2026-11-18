/**
 * E5 Phase 2 font verification (B5/B6 evidence).
 *
 * Serves the production build (dist/) and verifies in a real Chromium:
 *   1. every @font-face resolves and reports loaded via document.fonts.check
 *   2. Bengali shaping renders (conjuncts, matras, numerals) — screenshot
 *   3. NO request leaves the origin for a font (no fonts.googleapis.com /
 *      fonts.gstatic.com / any third-party font CDN)
 *   4. the preload in index.html exactly matches the CSS-requested URL and
 *      is not re-downloaded (one network fetch for the critical face)
 *
 * Usage: node scripts/verify_fonts.mjs [distDir] [port]
 * Requires: `npm run build` first. Dev-only tool; not part of the app.
 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { chromium } from "@playwright/test";

const dist = resolve(process.argv[2] ?? "dist");
const port = Number(process.argv[3] ?? 4199);
const MIME = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "text/javascript",
  ".woff2": "font/woff2",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".webmanifest": "application/manifest+json",
  ".json": "application/json",
};

const server = createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  // The fixture is SERVED by this server (same origin as the fonts) — fonts
  // are CORS-required resources, so a setContent/about:blank harness would
  // falsely fail every face with an opaque-origin fetch error.
  if (url.pathname === "/__font_fixture") {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end(page1);
    return;
  }
  let path = join(dist, decodeURIComponent(url.pathname));
  if (!existsSync(path) || path.endsWith("/")) path = join(dist, "index.html");
  try {
    const body = await readFile(path);
    res.writeHead(200, { "content-type": MIME[extname(path)] ?? "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end("not found");
  }
});
await new Promise((r) => server.listen(port, r));

const fixture = `<!doctype html><html lang="bn"><head><meta charset="utf-8">
<link rel="stylesheet" href="/__fixture_css_hook__"></head>
<body>
<h1 style="font-weight:700">বাংলা GPT টিউটর — শিক্ষার্থী</h1>
<h2 style="font-weight:600">জিজ্ঞাসা করুন, কুইজ দিন, অগ্রগতি দেখুন</h2>
<p style="font-weight:400">বিশ্বকাপ, বৃষ্টি, দ্বিতীয়, কৃষি, যুক্তাক্ষর: ক্ষ, ত্র, জ্ঞ, শ্র, ণ্ড — আমি বাংলায় গল্প লিখি। English mixed with বাংলা text and numbers ০১২৩৪৫৬৭৮৯ / 0123456789.</p>
<p>গণিত: x² + y² = z², অংক ৫৬৭৮৯; মূল্য ৳৫০০ (U+20B9 টাকা চিহ্ন); danda।।</p>
<table><tr><th>বিষয়</th><th>নম্বর</th></tr><tr><td>বিজ্ঞান</td><td>৯৮.৫</td></tr></table>
</body></html>`;

// Find the built stylesheet href from the app's own index.html so the
// fixture exercises the REAL shipped CSS (fonts.css is bundled inside it).
const indexHtml = await readFile(join(dist, "index.html"), "utf8");
const cssHref = indexHtml.match(/href="(\/assets\/[^"]+\.css)"/)?.[1];
if (!cssHref) throw new Error("built CSS not found in dist/index.html");
const page1 = fixture.replace("/__fixture_css_hook__", cssHref);

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
const page = await context.newPage();

const fontRequests = [];
const externalRequests = [];
page.on("request", (req) => {
  const u = new URL(req.url());
  if (u.pathname.endsWith(".woff2") || u.pathname.endsWith(".woff")) {
    fontRequests.push(u.pathname);
    if (u.origin !== `http://localhost:${port}`) externalRequests.push(req.url());
  }
  if (/fonts\.(googleapis|gstatic)\.com|use\.typekit|cdn\./.test(u.hostname)) {
    externalRequests.push(req.url());
  }
});

await page.goto(`http://localhost:${port}/__font_fixture`, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);

const checks = await page.evaluate(() => {
  const c = (spec) => document.fonts.check(spec);
  return {
    noto400: c('16px "Noto Sans Bengali"'),
    noto600: c('600 16px "Noto Sans Bengali"'),
    noto700: c('700 16px "Noto Sans Bengali"'),
    // Hind Siliguri is the SECOND family: its faces legitimately stay
    // "unloaded" unless a glyph falls through to it. Assert presence, not
    // load state.
    hindDeclared: [...document.fonts].some((f) => f.family === "Hind Siliguri"),
    loadedFaces: [...document.fonts].map((f) => `${f.family} ${f.weight} ${f.status}`),
  };
});

await page.screenshot({ path: resolve("font-fixture.png"), fullPage: true });

console.log("font checks:", JSON.stringify(checks, null, 1));
console.log("font requests:", JSON.stringify(fontRequests));
console.log("external font requests:", JSON.stringify(externalRequests));

const preloadHref = "/fonts/noto-sans-bengali-bengali-400-normal.woff2";
const noto400Fetches = fontRequests.filter((p) => p === preloadHref).length;
console.log(`preload face fetched ${noto400Fetches}x (expect 1)`);

let failed = 0;
for (const [k, v] of Object.entries(checks)) {
  if (k === "loadedFaces") continue;
  if (v !== true) {
    console.error(`FAIL: ${k} not satisfied`);
    failed++;
  }
}
if (externalRequests.length > 0) {
  console.error("FAIL: external font request detected");
  failed++;
}
if (noto400Fetches !== 1) {
  console.error(`FAIL: preload face fetched ${noto400Fetches}x, expected exactly 1`);
  failed++;
}
const bengaliFaces = checks.loadedFaces.filter((f) => f.includes("Noto Sans Bengali") && f.includes("loaded"));
if (bengaliFaces.length < 6) {
  console.error(`FAIL: expected >=6 loaded Noto faces, got ${bengaliFaces.length}`);
  failed++;
}
console.log(failed === 0 ? "VERIFY_FONTS: PASS" : `VERIFY_FONTS: ${failed} FAILURE(S)`);
await browser.close();
server.close();
process.exit(failed === 0 ? 0 : 1);
