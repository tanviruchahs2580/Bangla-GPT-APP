import { describe, expect, it } from "vitest";
import {
  formatServerDate,
  formatServerDateTime,
  parseServerDate,
} from "../lib/datetime";
import { localeFor } from "../lib/digits";

describe("parseServerDate", () => {
  it("reads an offset-less API timestamp as UTC, not as local time", () => {
    // The backend serialises naive UTC (datetime.now(UTC).replace(tzinfo=None))
    // as "2026-10-20T04:30:00". `new Date()` would read that as 04:30 local,
    // which is why deadlines rendered hours out for anyone outside UTC.
    const parsed = parseServerDate("2026-10-20T04:30:00");
    expect(parsed?.toISOString()).toBe("2026-10-20T04:30:00.000Z");
  });

  it("matches what a plain new Date does, only with the offset restored", () => {
    expect(parseServerDate("2026-10-20T04:30:00")?.getTime()).toBe(
      new Date("2026-10-20T04:30:00Z").getTime(),
    );
  });

  it("leaves a timestamp that already carries an offset alone", () => {
    for (const value of [
      "2026-10-20T04:30:00Z",
      "2026-10-20T04:30:00+06:00",
      "2026-10-20T04:30:00.500Z",
    ]) {
      expect(parseServerDate(value)?.getTime()).toBe(new Date(value).getTime());
    }
    expect(parseServerDate("2026-10-20T10:30:00+06:00")?.toISOString()).toBe(
      "2026-10-20T04:30:00.000Z",
    );
  });

  it("returns null for missing or unparseable values instead of an Invalid Date", () => {
    expect(parseServerDate(null)).toBeNull();
    expect(parseServerDate(undefined)).toBeNull();
    expect(parseServerDate("")).toBeNull();
    expect(parseServerDate("not a date")).toBeNull();
    expect(formatServerDateTime("not a date")).toBe("");
    expect(formatServerDate(null)).toBe("");
  });

  it("formats in the app locale, in the viewer's zone", () => {
    // Whatever the machine's zone, the instant must survive the round trip:
    // the formatted output has to equal the same instant formatted directly.
    // AUD-G-15: the locale is the APP's (localeFor()), not the browser
    // default -- a Bangla screen renders ১৮/১০/২০২৬ rather than 18/10/2026 --
    // so the expectation formats with the same locale the component uses.
    const instant = new Date("2026-10-20T04:30:00Z");
    const locale = localeFor();
    expect(formatServerDateTime("2026-10-20T04:30:00")).toBe(
      instant.toLocaleString(locale),
    );
    expect(
      formatServerDate("2026-10-20T04:30:00", {
        day: "numeric",
        month: "short",
      }),
    ).toBe(
      instant.toLocaleDateString(locale, { day: "numeric", month: "short" }),
    );
  });
});
