/**
 * WAVE-4 tooling: regenerate raster icons from the vector sources.
 * - public/icon-192.png / icon-512.png  ← public/icon.svg
 * - android mipmap ic_launcher(+round)  ← public/icon.svg
 * - android mipmap ic_launcher_foreground ← public/icon-maskable.svg
 * Usage: node scripts/gen-icons.mjs   (requires @resvg/resvg-js)
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Resvg } from "@resvg/resvg-js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const iconSvg = readFileSync(join(root, "public", "icon.svg"));
const maskSvg = readFileSync(join(root, "public", "icon-maskable.svg"));

function render(svg, width) {
  return new Resvg(svg, { fitTo: { mode: "width", value: width } })
    .render()
    .asPng();
}

const targets = [
  // [file, svg, width]
  [join(root, "public", "icon-192.png"), iconSvg, 192],
  [join(root, "public", "icon-512.png"), iconSvg, 512],
];
const MIPMAP = { mdpi: 48, hdpi: 72, xhdpi: 96, xxhdpi: 144, xxxhdpi: 192 };
const FOREGROUND = {
  mdpi: 108,
  hdpi: 162,
  xhdpi: 216,
  xxhdpi: 324,
  xxxhdpi: 432,
};
for (const [dpi, size] of Object.entries(MIPMAP)) {
  const dir = join(root, "android", "app", "src", "main", "res", `mipmap-${dpi}`);
  targets.push([join(dir, "ic_launcher.png"), iconSvg, size]);
  targets.push([join(dir, "ic_launcher_round.png"), iconSvg, size]);
}
for (const [dpi, size] of Object.entries(FOREGROUND)) {
  const dir = join(root, "android", "app", "src", "main", "res", `mipmap-${dpi}`);
  targets.push([join(dir, "ic_launcher_foreground.png"), maskSvg, size]);
}

for (const [file, svg, width] of targets) {
  writeFileSync(file, render(svg, width));
  console.log("wrote", file, `${width}px`);
}
