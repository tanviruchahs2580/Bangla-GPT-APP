/**
 * PWA-01: the manifest is the install contract. Chromium's installability
 * criteria pass without `id`/`scope`, but the install identity then derives
 * from `start_url`, so a future change can split an existing install from its
 * data — and the completeness list FE/PWA-01 checks requires both keys.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

interface ManifestIcon {
  src: string;
  sizes: string;
  type: string;
  purpose?: string;
}

interface Manifest {
  name: string;
  short_name: string;
  id?: string;
  scope?: string;
  start_url: string;
  display: string;
  lang: string;
  icons: ManifestIcon[];
}

// import.meta.url is not a file: URL under the jsdom environment, so the
// manifest is located from the package root (same note as serviceWorker.test.ts).
const manifest = JSON.parse(
  readFileSync(join(process.cwd(), "public", "manifest.webmanifest"), "utf8"),
) as Manifest;

describe("public/manifest.webmanifest", () => {
  it("pins the install identity with id and scope", () => {
    expect(manifest.id).toBe("/");
    expect(manifest.scope).toBe("/");
    // id must stay inside scope, or the browser refuses the manifest.
    expect(manifest.id?.startsWith(manifest.scope ?? "")).toBe(true);
  });

  it("keeps start_url inside the scope", () => {
    expect(manifest.start_url.startsWith(manifest.scope ?? "")).toBe(true);
  });

  it("ships any-purpose 192/512 PNGs and a maskable icon", () => {
    const png = manifest.icons.filter((i) => i.type === "image/png");
    expect(png.map((i) => i.sizes)).toEqual(
      expect.arrayContaining(["192x192", "512x512"]),
    );
    expect(
      manifest.icons.some((i) => (i.purpose ?? "").includes("maskable")),
    ).toBe(true);
  });

  it("declares the Bangla display contract", () => {
    expect(manifest.lang).toBe("bn");
    expect(manifest.display).toBe("standalone");
  });
});
