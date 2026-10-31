import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { byClassLevelThenSection, localizedCollator } from "../lib/localeSort";

// F-116: the teacher section sorts used a bare `localeCompare`, so the order
// followed the device locale instead of the app language.
describe("localized name/section sorts", () => {
  afterEach(() => setLang("bn"));

  it("builds the collator from the app language, not the device", () => {
    expect(localizedCollator("bn").resolvedOptions().locale).toMatch(/^bn/);
    expect(localizedCollator("en").resolvedOptions().locale).toMatch(/^en/);
    setLang("en");
    expect(localizedCollator().resolvedOptions().locale).toMatch(/^en/);
    setLang("bn");
    expect(localizedCollator().resolvedOptions().locale).toMatch(/^bn/);
  });

  it("orders classrooms by level, then section, without mutating the input", () => {
    const rows = [
      { class_level: 9, section: "খ" },
      { class_level: 6, section: "গ" },
      { class_level: 6, section: "ক" },
    ];
    const ordered = byClassLevelThenSection(rows);
    expect(ordered.map((r) => `${r.class_level}${r.section}`)).toEqual([
      "6ক",
      "6গ",
      "9খ",
    ]);
    // The query cache's array must survive the select intact.
    expect(rows.map((r) => r.section)).toEqual(["খ", "গ", "ক"]);
    expect(ordered).not.toBe(rows);
  });

  it("keeps the classroom pages on the shared sort", () => {
    for (const file of ["AssessmentsPage.tsx", "ClassesPage.tsx"]) {
      const source = readFileSync(
        resolve(process.cwd(), "src", "pages", "teacher", file),
        "utf8",
      );
      expect(
        source,
        `${file} must sort sections through byClassLevelThenSection`,
      ).toContain("byClassLevelThenSection");
      expect(
        source,
        `${file} still sorts with a device-locale localeCompare`,
      ).not.toMatch(/\.localeCompare\(/);
    }
  });
});
