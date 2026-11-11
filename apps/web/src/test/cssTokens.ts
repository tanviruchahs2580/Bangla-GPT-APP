/**
 * Shared helpers for the CSS-token guards (`contrastTokens.test.ts`,
 * `formControlBoundary.test.ts`).
 *
 * WHY THIS MODULE EXISTS
 *
 * Both guards used to locate their token block with
 * `css.indexOf(":root {")` / `css.indexOf('[data-theme="dark"] {')`. That
 * resolves to the FIRST match only. styles.css declares four blocks --
 * `:root` and `[data-theme="dark"]` twice each (the v3 base pair, then the
 * v3-extended pair further down the file) -- so eleven light tokens and six
 * dark tokens were invisible to every ratio computation in the repository.
 * Nothing was wrong with the assertions; they simply never saw a third of the
 * palette.
 *
 * It was also a latent trap rather than a cosmetic one: the second `:root`
 * sits AFTER the first `[data-theme="dark"]` block at equal specificity, so a
 * token added there under a name that already exists in dark mode would have
 * silently overridden dark mode with no test failing.
 *
 * `themeTokens()` therefore merges EVERY block per theme, in source order,
 * which is what the cascade actually does.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect } from "vitest";

export type Tokens = Record<string, string>;

export function readStyles(): string {
  return readFileSync(resolve(process.cwd(), "src", "styles.css"), "utf8");
}

/** Strip CSS comments without moving any newline, so line numbers quoted in a
 *  failure message still point at the real file. */
function maskComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, (b) => b.replace(/[^\n]/g, " "));
}

/**
 * All token blocks for one theme, merged in source order (later wins, as the
 * cascade does). Brace-depth aware, so a value containing `}` cannot end a
 * block early.
 */
function collect(css: string, selector: string): Tokens {
  const body = maskComments(css);
  const out: Tokens = {};
  const re = new RegExp(`${selector}\\s*\\{`, "g");
  for (const hit of body.matchAll(re)) {
    let i = hit.index + hit[0].length;
    let depth = 1;
    while (i < body.length && depth > 0) {
      if (body[i] === "{") depth += 1;
      else if (body[i] === "}") depth -= 1;
      i += 1;
    }
    for (const d of body
      .slice(hit.index + hit[0].length, i - 1)
      .matchAll(/--([a-z0-9-]+)\s*:\s*([^;]+);/g)) {
      out[d[1]] = d[2].trim();
    }
  }
  return out;
}

/** `{ light, dark }`, dark inheriting light then overriding -- exactly how
 *  `[data-theme="dark"]` behaves at runtime. */
export function themeTokens(css: string): { light: Tokens; dark: Tokens } {
  const light = collect(css, ":root");
  return {
    light,
    dark: { ...light, ...collect(css, '\\[data-theme="dark"\\]') },
  };
}

/** How many distinct blocks each theme's tokens were gathered from. Used by
 *  the guard that asserts the parser can still see every block. */
export function blockCounts(css: string): { light: number; dark: number } {
  const body = maskComments(css);
  return {
    light: [...body.matchAll(/:root\s*\{/g)].length,
    dark: [...body.matchAll(/\[data-theme="dark"\]\s*\{/g)].length,
  };
}

// --------------------------------------------------------------------- colour
export function toRgb(hex: string): [number, number, number] {
  const h = hex.trim().replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [
    number,
    number,
    number,
  ];
}

export function channel(c: number): number {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const [r, g, b] = toRgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function ratio(fg: string, bg: string): number {
  const [lo, hi] = [luminance(fg), luminance(bg)].sort((a, b) => a - b);
  return (hi + 0.05) / (lo + 0.05);
}

/** `rgba(255,255,255,alpha)` composited over a fill -- .btn-primary/.btn-teal
 *  layer a 14% white highlight on their top edge. Returns bare hex. */
export function overWhite(hex: string, alpha: number): string {
  const comp = toRgb(hex).map((c) => c * (1 - alpha) + 255 * alpha);
  return comp.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("");
}

/** Resolve `var(--x)` chains to a literal value from a token map. */
export function resolveToken(
  tokens: Tokens,
  name: string,
  seen: string[] = [],
): string {
  expect(name in tokens, `no token --${name}`).toBe(true);
  if (seen.includes(name)) throw new Error(`circular --${name}`);
  const raw = tokens[name];
  const m = raw.match(/^var\(\s*--([a-z0-9-]+)\s*\)$/);
  return m ? resolveToken(tokens, m[1], [...seen, name]) : raw;
}

// ----------------------------------------------------------------- rules
/** Bodies of every rule whose selector, whitespace-collapsed, EQUALS
 *  `selector`. Exact matching matters: a substring search for `::placeholder`
 *  also matches `.hero .home-prompt .input::placeholder`, because the shorter
 *  selector is a suffix of the longer one. */
export function rulesForSelector(css: string, selector: string): string[] {
  const wanted = selector.replace(/\s+/g, " ").trim();
  const bodies = [...maskComments(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter((m) => m[1].replace(/\s+/g, " ").trim() === wanted)
    .map((m) => m[2]);
  expect(bodies.length, `no rule for ${selector}`).toBeGreaterThan(0);
  return bodies;
}

/**
 * Bodies of every rule whose selector LIST contains `selector` as one member.
 *
 * Grouped rules (`.voice-btn.recording::after, .voice-btn.voice-live::after`)
 * are why this exists -- exact matching misses them entirely. The split is
 * parenthesis-aware, because a member can itself contain a comma
 * (`.section-head :is(h1, h2)`), which a naive `split(",")` would shred.
 */
export function rulesMatchingMember(css: string, selector: string): string[] {
  const wanted = selector.replace(/\s+/g, " ").trim();
  const bodies = [...maskComments(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter((m) => splitSelectorList(m[1]).includes(wanted))
    .map((m) => m[2]);
  expect(bodies.length, `no rule listing ${selector}`).toBeGreaterThan(0);
  return bodies;
}

function splitSelectorList(list: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let current = "";
  for (const ch of list) {
    if (ch === "(") depth += 1;
    else if (ch === ")") depth -= 1;
    if (ch === "," && depth === 0) {
      out.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  out.push(current);
  return out.map((s) => s.replace(/\s+/g, " ").trim()).filter(Boolean);
}

/**
 * Token NAMES declared in each block, in source order, tagged by theme.
 *
 * Exists for the cascade-trap guard. `themeTokens()` merges every `:root` and
 * every dark block, which is right for reading values -- but CSS resolves a
 * token by *source position*, not by block kind. The second `:root` sits AFTER
 * the first dark block at equal specificity, so a name declared in both would
 * resolve to the LATER one in dark mode: the light block would win. The merged
 * map would report the dark value. Nothing overlaps today; this guard makes
 * sure a future edit cannot introduce that silently.
 */
export function tokenNamesByBlock(
  css: string,
): Array<{ theme: "light" | "dark"; names: string[] }> {
  const body = maskComments(css);
  const out: Array<{ theme: "light" | "dark"; names: string[] }> = [];
  for (const hit of body.matchAll(/(:root|\[data-theme="dark"\])\s*\{/g)) {
    let i = hit.index + hit[0].length;
    let depth = 1;
    while (i < body.length && depth > 0) {
      if (body[i] === "{") depth += 1;
      else if (body[i] === "}") depth -= 1;
      i += 1;
    }
    const names = [
      ...body
        .slice(hit.index + hit[0].length, i - 1)
        .matchAll(/--([a-z0-9-]+)\s*:/g),
    ].map((m) => m[1]);
    out.push({
      theme: hit[1] === ":root" ? "light" : "dark",
      names,
    });
  }
  return out;
}
