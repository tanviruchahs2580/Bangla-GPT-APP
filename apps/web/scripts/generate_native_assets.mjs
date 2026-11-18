/**
 * E5/native-assets workstream: generate every PNG raster the PWA and the
 * Capacitor Android project need from the ONE approved brand mark
 * (public/icon.svg + public/icon-maskable.svg). No new artwork is invented
 * here — this is pure conversion:
 *
 *   - PWA maskable PNGs (192/512) from icon-maskable.svg (the mark already
 *     sits inside the maskable safe zone in that source).
 *   - Android legacy launcher + round PNGs per density from icon.svg.
 *   - Android adaptive-icon FOREGROUND layers: the mark WITHOUT its rounded
 *     square, scaled to 0.66 (the adaptive safe zone is the inner 66/108 dp)
 *     on transparency. The BACKGROUND layer is a drawable gradient XML
 *     (brand colors) — see res/drawable/ic_launcher_background.xml.
 *   - Android splash drawables: brand background #f4f6fd with the mark
 *     centred, replacing the Capacitor template splash at every density and
 *     orientation the generated project ships.
 *
 * Deterministic: same inputs -> same PNGs. Rasterisation is Playwright
 * chromium (already a dev dependency) with omitBackground for transparency.
 *
 * Usage: node scripts/generate_native_assets.mjs
 */
import { readFile, writeFile } from "node:fs/promises";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { chromium } from "@playwright/test";

const ROOT = resolve(import.meta.dirname, "..");
const PUBLIC = resolve(ROOT, "public");
const RES = resolve(ROOT, "android", "app", "src", "main", "res");
const BRAND_BG = "#f4f6fd"; // app background (capacitor.config.ts)

const iconSvg = await readFile(resolve(PUBLIC, "icon.svg"), "utf8");
const maskableSvg = await readFile(resolve(PUBLIC, "icon-maskable.svg"), "utf8");

/** The mark = icon.svg minus its rounded-square background rect. */
const mark = iconSvg
  .replace(/<rect[^>]*\/>/, "")
  .replace('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">', "")
  .replace("</svg>", "");

/** Adaptive foreground: mark only, scaled into the 66/108 safe zone. */
const foregroundSvg = (size) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 512 512"><g transform="translate(256 256) scale(0.66) translate(-256 -256)">${mark}</g></svg>`;

/** Splash: brand background with the mark centred at 30% of the short side. */
const splashSvg = (w, h) => {
  const s = (Math.min(w, h) * 0.3) / 512;
  const cx = w / 2;
  const cy = h / 2;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><rect width="${w}" height="${h}" fill="${BRAND_BG}"/><g transform="translate(${cx} ${cy}) scale(${s}) translate(-256 -256)">${mark}</g></svg>`;
};

const sized = (svgSource, w, h) =>
  svgSource
    .replace('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">', `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 512 512">`);

const jobs = [];

async function render(svgMarkup, w, h, outPath, { transparent = false } = {}) {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({
      viewport: { width: w, height: h },
      deviceScaleFactor: 1,
    });
    await page.setContent(
      `<!doctype html><html><body style="margin:0;padding:0;background:${transparent ? "transparent" : "white"}">${svgMarkup}</body></html>`,
    );
    await page.screenshot({
      path: outPath,
      omitBackground: transparent,
      clip: { x: 0, y: 0, width: w, height: h },
    });
  } finally {
    await browser.close();
  }
  jobs.push(`${outPath.replace(ROOT + "/", "")} (${w}x${h}${transparent ? ", alpha" : ""})`);
}

async function writeText(outPath, content) {
  mkdirSync(dirname(outPath), { recursive: true });
  await writeFile(outPath, content);
  jobs.push(`${outPath.replace(ROOT + "/", "")} (text)`);
}

// ---- PWA maskable PNGs (the manifest currently has SVG-only maskable) ----
for (const size of [192, 512]) {
  await render(
    sized(maskableSvg, size, size),
    size,
    size,
    resolve(PUBLIC, `icon-${size}-maskable.png`),
  );
}

// ---- Android legacy launcher + round icons per density ----
const launcherDensities = [
  ["mdpi", 48],
  ["hdpi", 72],
  ["xhdpi", 96],
  ["xxhdpi", 144],
  ["xxxhdpi", 192],
];
for (const [density, size] of launcherDensities) {
  for (const name of ["ic_launcher", "ic_launcher_round"]) {
    // transparent: the rounded-square's corners must stay transparent — the
    // launcher applies its own shaping; opaque white corners would show.
    await render(
      sized(iconSvg, size, size),
      size,
      size,
      resolve(RES, `mipmap-${density}`, `${name}.png`),
      { transparent: true },
    );
  }
}

// ---- Android adaptive foreground layers (transparent, mark in safe zone) ----
const fgDensities = [
  ["mdpi", 108],
  ["hdpi", 162],
  ["xhdpi", 216],
  ["xxhdpi", 324],
  ["xxxhdpi", 432],
];
for (const [density, size] of fgDensities) {
  await render(
    foregroundSvg(size),
    size,
    size,
    resolve(RES, `mipmap-${density}`, "ic_launcher_foreground.png"),
    { transparent: true },
  );
}

// ---- Android splash drawables (replace the Capacitor template splash) ----
const splashSizes = [
  ["drawable", 480, 320],
  ["drawable-port-mdpi", 320, 480],
  ["drawable-port-hdpi", 480, 800],
  ["drawable-port-xhdpi", 720, 1280],
  ["drawable-port-xxhdpi", 960, 1600],
  ["drawable-port-xxxhdpi", 1280, 1920],
  ["drawable-land-mdpi", 480, 320],
  ["drawable-land-hdpi", 800, 480],
  ["drawable-land-xhdpi", 1280, 720],
  ["drawable-land-xxhdpi", 1600, 960],
  ["drawable-land-xxxhdpi", 1920, 1280],
];
for (const [dir, w, h] of splashSizes) {
  await render(splashSvg(w, h), w, h, resolve(RES, dir, "splash.png"));
}

// ---- Adaptive-icon XML: gradient background drawable + updated refs ----
await writeText(
  resolve(RES, "drawable", "ic_launcher_background.xml"),
  `<?xml version="1.0" encoding="utf-8"?>
<!-- Brand gradient background for the adaptive icon (E5/native-assets
     workstream): the same stops as the approved mark's rounded square
     (public/icon.svg), rendered as a drawable so every mask size gets the
     full-bleed gradient instead of the previous flat white. -->
<shape xmlns:android="http://schemas.android.com/apk/res/android">
    <gradient
        android:type="linear"
        android:angle="315"
        android:startColor="#16a34a"
        android:centerColor="#166534"
        android:endColor="#052e16"/>
</shape>
`,
);
for (const name of ["ic_launcher.xml", "ic_launcher_round.xml"]) {
  const p = resolve(RES, "mipmap-anydpi-v26", name);
  const xml = await readFile(p, "utf8");
  await writeText(
    p,
    xml.replace(
      '<background android:drawable="@color/ic_launcher_background"/>',
      '<background android:drawable="@drawable/ic_launcher_background"/>',
    ),
  );
}

console.log(`generated ${jobs.length} assets:`);
for (const j of jobs) console.log("  " + j);
