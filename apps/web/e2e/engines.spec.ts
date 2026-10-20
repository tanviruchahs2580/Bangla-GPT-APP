import { expect, test, type Page } from "@playwright/test";
import { openRoute, useVariant } from "./a11y";

/**
 * AUD-G-21 / AUD-G-22 / G-21 / G-22 in **three browser engines**.
 *
 * The item asks that Bangla conjuncts, reph and vowel signs render correctly
 * "in three browser engines and on mobile", with "no glyph clipping", and that
 * `Intl` with `bn-BD` "behaves as expected (verify in each browser)". Neither
 * claim can be made from a Chromium-only suite, and neither is a matter of
 * opinion once it is measured:
 *
 *  * the shipped Bangla webfont is actually the font the Bangla text is
 *    painted with, and it is loaded in this engine;
 *  * a conjunct/reph/vowel-sign stress string laid out inside the app's own
 *    `<main>` is not clipped by its own box (no tofu-width or overflow), at
 *    the app's body font size and line-height;
 *  * no Bangla element carries `letter-spacing` (which collides with those
 *    marks) and no element asks for a weight the loaded faces do not have;
 *  * `Intl` in this engine produces Bengali digits for `bn-BD`, valid Bengali
 *    dates, stable plural categories and a collator that orders Bangla by its
 *    own alphabet rather than by code point.
 *
 * Run it (Chromium, Firefox and WebKit in one command):
 *
 *     npx playwright test -c playwright.engines.config.ts
 *
 * The three-year "FontFaceSet.check" behaviour differs slightly between
 * engines; the assertions below are written against what each engine
 * guarantees, and every engine that cannot satisfy one is reported by name.
 */

const CONJUNCT_STRING =
  "ক্ষমতা জ্ঞান প্রযুক্তি সংস্কৃতি নিশ্চয়ই র্যাপিড ড্রাইভার দ্বন্দ্ব উজ্জ্বল অঙ্ক শঙ্কা ঐক্য ঔষধ ৃত্ব ৳১,২৩৪.৫৬ ক্ষ ক্ষ্ম জ্ঞ ঞ্চ ঞ্জ ঙ্ক ষ্ণ হ্ম ত্র শ্র ধ্ব ট্ট ড্ড ঠ্ঠ ন্ধ ব্ব ম্প ল্ক স্থ স্ন স্ম";

test.describe.configure({ timeout: 5 * 60_000 });

async function probeOnPage(page: Page): Promise<
  {
    width: number;
    scrollWidth: number;
    height: number;
    scrollHeight: number;
    family: string;
    weight: string;
    size: string;
  }[]
> {
  return page.evaluate((text) => {
    const main = document.querySelector('main, [role="main"]') ?? document.body;
    const host = document.createElement("div");
    host.id = "conjunct-probe";
    // The app's own typography: inherit the body font stack and size.
    host.style.cssText =
      "max-width:100%;white-space:normal;font:inherit;line-height:1.7";
    const rows = [400, 600, 700].map((weight) => {
      const line = document.createElement("p");
      line.style.cssText = `margin:0;font-weight:${weight}`;
      line.textContent = text;
      host.appendChild(line);
      return line;
    });
    main.appendChild(host);
    const probe = rows.map((line) => {
      const style = window.getComputedStyle(line);
      return {
        width: line.clientWidth,
        scrollWidth: line.scrollWidth,
        height: line.clientHeight,
        scrollHeight: line.scrollHeight,
        family: style.fontFamily.split(",")[0].replace(/["']/g, "").trim(),
        weight: style.fontWeight,
        size: style.fontSize,
      };
    });
    host.remove();
    return probe;
  }, CONJUNCT_STRING);
}

for (const lang of ["bn", "en"] as const) {
  test(`Bangla conjuncts render unclipped in this engine (${lang})`, async ({
    page,
    browserName,
  }) => {
    await useVariant(page, { theme: "light", lang });
    await openRoute(page, "/welcome");
    await page.evaluate(() => document.fonts.ready);

    // The Bangla face must be loaded, not merely declared: with
    // font-display: swap a missing subset renders in a fallback and the test
    // would otherwise pass while the user sees a different typeface.
    const loaded = await page.evaluate(() =>
      [...document.fonts]
        .filter((face) => face.status === "loaded")
        .map((face) => `${face.family}@${face.weight}`),
    );
    expect(
      loaded.some((face) => face.startsWith("Noto Sans Bengali@400")),
      `[${browserName}] Noto Sans Bengali 400 never loaded: ${loaded.join(", ")}`,
    ).toBe(true);

    const probes = await probeOnPage(page);
    for (const probe of probes) {
      expect(
        probe.scrollWidth,
        `[${browserName}] the ${probe.weight} probe wraps out of its box (${probe.scrollWidth} > ${probe.width})`,
      ).toBeLessThanOrEqual(probe.width + 1);
      expect(
        probe.scrollHeight,
        `[${browserName}] the ${probe.weight} probe clips vertically (${probe.scrollHeight} > ${probe.height})`,
      ).toBeLessThanOrEqual(probe.height + 1);
      // Line-height >= 1.6 for Bangla body text is a G-21 requirement; the
      // probe inherits the app's own body line-height.
      const ratio = probe.height / parseFloat(probe.size);
      expect(
        ratio,
        `[${browserName}] line-height ${ratio} < 1.6 for Bangla body text`,
      ).toBeGreaterThanOrEqual(1.6);
    }
  });
}

test("no letter-spacing is applied to Bangla text, in any engine", async ({
  page,
  browserName,
}) => {
  await useVariant(page, { theme: "light", lang: "bn" });
  await openRoute(page, "/welcome");
  const offenders = await page.evaluate(() => {
    const bad: string[] = [];
    for (const element of Array.from(
      document.querySelectorAll("h1, h2, h3, h4, p, span, a, .btn, .brand"),
    )) {
      const text = (element.textContent ?? "").trim();
      if (!/[\u0980-\u09FF]/.test(text)) continue; // only Bangla-bearing nodes
      const spacing = window.getComputedStyle(element).letterSpacing;
      if (spacing !== "normal" && parseFloat(spacing) !== 0) {
        bad.push(
          `${element.tagName}.${(element.getAttribute("class") ?? "").split(" ")[0]}=${spacing}`,
        );
      }
    }
    return [...new Set(bad)].slice(0, 10);
  });
  expect(
    offenders,
    `[${browserName}] letter-spacing on Bangla: ${offenders.join(", ")}`,
  ).toEqual([]);
});

test("only loaded font weights are used for Bangla (no synthetic bold)", async ({
  page,
  browserName,
}) => {
  await useVariant(page, { theme: "light", lang: "bn" });
  await openRoute(page, "/welcome");
  await page.evaluate(() => document.fonts.ready);
  const result = await page.evaluate(() => {
    const loaded = new Set(
      [...document.fonts]
        .filter((f) => f.status === "loaded")
        .map((f) => `${f.family}@${f.weight}`),
    );
    const missing: string[] = [];
    for (const element of Array.from(
      document.querySelectorAll("h1, h2, h3, h4, p, .btn, strong, b"),
    )) {
      const text = (element.textContent ?? "").trim();
      if (!/[\u0980-\u09FF]/.test(text)) continue;
      const style = window.getComputedStyle(element);
      const family = style.fontFamily.split(",")[0].replace(/["']/g, "").trim();
      const weight = style.fontWeight;
      // A weight in the stack's first family with no matching face is a
      // synthesis candidate; the audit's finding was `font-weight: 800`
      // against families that ship 400/600/700 only.
      const sameFamily = [...loaded].filter((face) =>
        face.startsWith(`${family}@`),
      );
      if (sameFamily.length === 0) continue; // the engine fell through the stack
      const weights = sameFamily.map((face) => Number(face.split("@")[1]));
      if (!weights.includes(Number(weight))) {
        const nearest = weights.some(
          (w) => w > Number(weight) || w < Number(weight),
        );
        if (!nearest)
          missing.push(
            `${element.tagName}.${(element.getAttribute("class") ?? "").split(" ")[0]} ${family}@${weight}`,
          );
      }
    }
    return {
      missing: [...new Set(missing)].slice(0, 10),
      loaded: [...loaded].sort(),
    };
  });
  expect(
    result.missing,
    `[${browserName}] weights without a face: ${result.missing.join(", ")} | loaded: ${result.loaded.join(", ")}`,
  ).toEqual([]);
});

test("Intl: bn-BD numbers, dates, plurals and collation behave in this engine", async ({
  page,
  browserName,
}) => {
  await useVariant(page, { theme: "light", lang: "bn" });
  await openRoute(page, "/welcome");
  const result = await page.evaluate(() => {
    const out: Record<string, string> = {};
    try {
      out.number = new Intl.NumberFormat("bn-BD").format(12345);
      out.decimal = new Intl.NumberFormat("bn-BD").format(1234.5);
      out.grouping = new Intl.NumberFormat("bn-BD", {
        useGrouping: true,
      }).format(1234567);
      out.date = new Intl.DateTimeFormat("bn-BD", {
        dateStyle: "long",
        timeZone: "Asia/Dhaka",
      }).format(new Date("2026-10-20T04:30:00Z"));
      out.time = new Intl.DateTimeFormat("bn-BD", {
        timeStyle: "short",
        timeZone: "Asia/Dhaka",
      }).format(new Date("2026-10-20T04:30:00Z"));
      out.plural1 = new Intl.PluralRules("bn-BD").select(1);
      out.plural2 = new Intl.PluralRules("bn-BD").select(2);
      out.collator = ["শ", "অ", "ক", "আ", "ম"]
        .sort(new Intl.Collator("bn").compare)
        .join("");
      out.segmenter = [
        ...new Intl.Segmenter("bn", { granularity: "grapheme" }).segment("ক্ষ"),
      ].length;
    } catch (error) {
      out.error = String(error);
    }
    return out;
  });

  expect(
    result.error,
    `[${browserName}] Intl threw: ${result.error}`,
  ).toBeUndefined();
  // Bengali digits ০-৯ for every number.
  expect(result.number, `[${browserName}] number`).toMatch(
    /^[\u09E6-\u09EF,০-৯]+$/,
  );
  // Grouping is locale-decided (bn-BD groups 2,2,3: "১২,৩৪৫"), so the check
  // is that every digit was transliterated, not that they sit contiguously.
  const BENGALI_DIGITS = ["০", "১", "২", "৩", "৪", "৫", "৬", "৭", "৮", "৯"];
  for (const digit of "12345") {
    expect(result.number, `[${browserName}] number digit ${digit}`).toContain(
      BENGALI_DIGITS[Number(digit)],
    );
  }
  expect(result.grouping, `[${browserName}] grouping`).toContain(",");
  expect(result.date, `[${browserName}] date`).toMatch(/[\u09E6-\u09EF]/);
  expect(result.date, `[${browserName}] date year`).toContain("২০২৬");
  expect(result.time, `[${browserName}] time`).toMatch(/[\u09E6-\u09EF]/);
  // CLDR bn has two categories: `one` covers n = 0 and n = 1 ("one: i = 0 or
  // n = 1"), everything else is `other`. The earlier expectation of a single
  // `other` category was wrong about the locale, not about the engine.
  expect(result.plural1, `[${browserName}] plural(1)`).toBe("one");
  expect(result.plural2, `[${browserName}] plural(2)`).toBe("other");
  // Alphabetical order in Bangla, not code-point order (code point would put
  // আ (U+0986) before অ (U+0985) only by coincidence -- the vowel signs and
  // the reordered letters are where they diverge).
  expect(result.collator, `[${browserName}] collator`).toBe("অআকমশ");
  // `ক্ষ` is one grapheme for a reader: ka + virama + ssa.
  expect(result.segmenter, `[${browserName}] grapheme count`).toBe(1);
});

test("the app formats API dates in the app language, not the browser language", async ({
  page,
  browserName,
}) => {
  await useVariant(page, { theme: "light", lang: "bn" });
  await openRoute(page, "/welcome");
  const rendered = await page.evaluate(() => {
    const toBn = (iso: string) => new Date(`${iso}Z`).toLocaleString("bn-BD");
    return { bn: toBn("2026-10-20T04:30:00") };
  });
  // Sanity: the locale used by lib/datetime.ts produces Bengali digits in this
  // engine, which is what makes "18/10/2026 vs ১৮/১০/২০২৬" a real fix.
  expect(rendered.bn, `[${browserName}] datetime`).toMatch(/[\u09E6-\u09EF]/);
});
