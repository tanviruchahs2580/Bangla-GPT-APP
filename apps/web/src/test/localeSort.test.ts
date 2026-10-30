import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { localizedCollator } from "../lib/localeSort";

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

  it("keeps the classroom pages off a bare localeCompare", () => {
    for (const file of ["AssessmentsPage.tsx", "ClassesPage.tsx"]) {
      const source = readFileSync(
        resolve(process.cwd(), "src", "pages", "teacher", file),
        "utf8",
      );
      expect(
        source,
        `${file} must sort sections through localizedCollator()`,
      ).toContain("localizedCollator()");
      expect(
        source,
        `${file} still sorts with a device-locale localeCompare`,
      ).not.toMatch(/\.localeCompare\(/);
    }
  });
});
