import { describe, expect, it } from "vitest";
import {
  formatServerDate,
  formatServerDateTime,
  parseServerDate,
} from "../lib/datetime";

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

  it("formats in the viewer's locale zone", () => {
    // Whatever the machine's zone, the instant must survive the round trip:
    // the formatted output has to equal the same instant formatted directly.
    const instant = new Date("2026-10-20T04:30:00Z");
    expect(formatServerDateTime("2026-10-20T04:30:00")).toBe(
      instant.toLocaleString(),
    );
    expect(
      formatServerDate("2026-10-20T04:30:00", {
        day: "numeric",
        month: "short",
      }),
    ).toBe(
      instant.toLocaleDateString(undefined, { day: "numeric", month: "short" }),
    );
  });
});
