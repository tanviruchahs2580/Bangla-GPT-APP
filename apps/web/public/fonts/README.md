# Self-hosted UI webfonts — provenance and regeneration

E5 Phase 2 (2026-11-18). These binaries are the app's UI webfonts, vendored
verbatim from the installed `@fontsource` packages (which repackage the
Google Fonts originals) so the app no longer depends on that package at
build or runtime. Both families are licensed under the **SIL Open Font
License 1.1** — the full licence text ships next to the binaries
(`LICENSE-*.txt`), as OFL 1.1 §2 requires for every copy. Copyright holders:

- `noto-sans-bengali-*` — The Noto Project Authors (github.com/notofonts/bengali)
- `hind-siliguri-*` — Indian Type Foundry (info@indiantypefoundry.com), 2015

## What is shipped

Bengali + latin subsets, woff2 only, for exactly the weights the UI imports:

| File | Weight | Bytes |
|---|---|---|
| noto-sans-bengali-bengali-400-normal.woff2 | 400 | 44,352 |
| noto-sans-bengali-bengali-600-normal.woff2 | 600 | 47,636 |
| noto-sans-bengali-bengali-700-normal.woff2 | 700 | 47,788 |
| noto-sans-bengali-latin-400-normal.woff2 | 400 | 10,352 |
| noto-sans-bengali-latin-600-normal.woff2 | 600 | 10,468 |
| noto-sans-bengali-latin-700-normal.woff2 | 700 | 10,408 |
| hind-siliguri-bengali-400-normal.woff2 | 400 | 71,076 |
| hind-siliguri-bengali-600-normal.woff2 | 600 | 74,784 |
| hind-siliguri-latin-400-normal.woff2 | 400 | 14,472 |
| hind-siliguri-latin-600-normal.woff2 | 600 | 14,724 |

Deliberately NOT shipped: the latin-ext subsets (no shipped string or
realistic tutor output uses U+0100–02BA; uncovered codepoints fall to the
system stack) and the legacy `.woff` duplicates (every supported engine
takes the woff2 source; the duplicates were dead weight in every APK).

## SHA-256 (verify after any regeneration)

```
8ae56aab7628191d874faef495d5229138187e8ed6061ede100fe362104faa91  hind-siliguri-bengali-400-normal.woff2
b92b5da6d4f4f6de315f093f26a4e20d7ce7876a7db3ae7dda6a92fc5c3cc7c4  hind-siliguri-bengali-600-normal.woff2
cdc41415f366ef2966fc77e90d51391dec03657a6ed397fe59efd5ce34cf9549  hind-siliguri-latin-400-normal.woff2
c39d0db6f570276765a06728ce87d83be5808ae403475ed6b49a64c02915805c  hind-siliguri-latin-600-normal.woff2
adb805ae2eb639cc5d7276ee0e3798a8092fbfe02a6e5a0e19d82587680b528c  noto-sans-bengali-bengali-400-normal.woff2
abfa65f4f73d0fab61667ad7a29ed1f96d143c2c7a8323ab04d0697d858a4d90  noto-sans-bengali-bengali-600-normal.woff2
67ffaf548d85c2022569374b5401cd8d296a2434c2df4b57399c31f9118ce8c3  noto-sans-bengali-bengali-700-normal.woff2
787cb67c208f5b16d2e636c6b865d8b44cb4223cb7861346d27577346c1c2010  noto-sans-bengali-latin-400-normal.woff2
8c3e19dc82cea1797b2f0ed19c807750ce1c751e11e82c717494c5728f9004fa  noto-sans-bengali-latin-600-normal.woff2
d04b9c030fbdaf5e749c2f3ed421068c21af32213da97f1e2d431dd9d5e5f48d  noto-sans-bengali-latin-700-normal.woff2
```

## Regeneration (only if a face is ever upgraded)

The binaries come from the `@fontsource/*` npm packages' `files/`
directory — never from a font mirror site. To refresh:

1. Temporarily re-add the package at the desired version
   (`npm i --no-save @fontsource/noto-sans-bengali@X.Y.Z`).
2. Copy the needed `files/<family>-<subset>-<weight>-normal.woff2` into
   this directory, plus the package `LICENSE` as `LICENSE-<family>.txt`.
3. Remove the temp package, update the SHA-256 table above, update the
   `@font-face` blocks + fallback descriptors in `src/fonts.css`
   (re-measure with `python scripts/font_metrics.py`), and update
   `THIRD_PARTY_NOTICES.md`.

The `@font-face` declarations live in `src/fonts.css`; the preload for the
critical first-paint face (`noto-sans-bengali-bengali-400`) lives in
`index.html`. Both reference these stable `/fonts/...` paths — no build
hash, so the preload can never go stale across deploys.
