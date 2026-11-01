import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// F-105 / F-106: the stylesheet's typography rules for Bangla are checked
// statically because the engine e2e spec only visits one public route and
// cannot see the authenticated chrome. The rules pinned here are the ones the
// audit measured: tracking on Bangla-bearing classes, weights the loaded
// families do not ship, and a line-height the matras cannot live in.
//
// vitest runs with cwd = apps/web (the package root), where import.meta.url
// is not a file: URL under jsdom; the other stylesheet guards resolve the same
// way (contrastTokens.test.ts).
const ROOT = resolve(process.cwd(), "src");
const css = readFileSync(resolve(ROOT, "styles.css"), "utf8");
const mainTsx = readFileSync(resolve(ROOT, "main.tsx"), "utf8");

/** Comments out of the way, so a declaration text can be attributed. */
const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");

/** The selector of the rule that contains `index`. */
function selectorAt(index: number): string {
  const open = stripped.lastIndexOf("{", index);
  const previousClose = stripped.lastIndexOf("}", open);
  return stripped
    .slice(previousClose + 1, open)
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith("@"))
    .join(" ");
}

type Declaration = { selector: string; value: string };

function declarations(property: string): Declaration[] {
  const out: Declaration[] = [];
  for (const match of stripped.matchAll(
    new RegExp(`${property}\\s*:\\s*([^;]+);`, "g"),
  )) {
    out.push({
      selector: selectorAt(match.index ?? 0),
      value: match[1].trim(),
    });
  }
  return out;
}

// Selectors that carry Latin machine values only, so tracking is safe there.
// .invite-code renders server-generated invite codes; .ring-inner renders the
// Latin-digit percentage inside the progress ring (all call sites pass
// `{Math.round(x)}%`).
const LATIN_ONLY_TRACKING = [".invite-code", ".ring-inner"];

describe("Bangla typography in styles.css", () => {
  it("applies letter-spacing only under :lang(en) or to Latin-only classes", () => {
    const offenders = declarations("letter-spacing")
      .filter(({ value }) => value !== "normal" && parseFloat(value) !== 0)
      .filter(
        ({ selector }) =>
          !selector.includes(":lang(en)") &&
          !LATIN_ONLY_TRACKING.some((allowed) => selector.includes(allowed)),
      )
      .map(({ selector, value }) => `${selector} { letter-spacing: ${value} }`);
    expect(offenders, "tracking on Bangla text").toEqual([]);
  });

  it("requests only weights the loaded families can serve without synthesis", () => {
    // main.tsx is the inventory of loaded faces. The first family in --font
    // (Noto Sans Bengali) must cover every weight the stylesheet asks for:
    // a request inside [400, 700] resolves to a real face (600 -> 700), while
    // the audit's 14 font-weight: 800 rules had no face at or above them --
    // an engine that synthesises bold would smear Bangla matras (F-105).
    const notoWeights = [...mainTsx.matchAll(/noto-sans-bengali\/(\d+)\.css/g)]
      .map((m) => Number(m[1]))
      .sort((a, b) => a - b);
    expect(notoWeights).toEqual([400, 700]);

    const requested = declarations("font-weight")
      .map(({ value }) => (value === "bold" ? 700 : Number(value)))
      .filter((weight) => !Number.isNaN(weight));
    const outside = requested.filter(
      (weight) =>
        weight < notoWeights[0] || weight > notoWeights[notoWeights.length - 1],
    );
    expect(outside, "weights outside the loaded range").toEqual([]);
  });

  it("never synthesises a weight or a slant", () => {
    expect(stripped).toMatch(/font-synthesis:\s*none/);
  });

  it("keeps hyphenation off and the Bangla line heights above the floor", () => {
    expect(stripped).not.toMatch(/hyphens:\s*auto/);
    const token = (name: string) => {
      const match = stripped.match(new RegExp(`${name}\\s*:\\s*([\\d.]+)`));
      expect(match, `${name} is missing`).not.toBeNull();
      return parseFloat(match?.[1] ?? "0");
    };
    expect(token("--lh-body")).toBeGreaterThanOrEqual(1.6);
    expect(token("--lh-head")).toBeGreaterThanOrEqual(1.5);
  });
});
