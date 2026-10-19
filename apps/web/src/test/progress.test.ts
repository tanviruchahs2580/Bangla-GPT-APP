import { describe, expect, it } from "vitest";
import { chapterBadge } from "../lib/progress";

describe("chapter badge logic", () => {
  it("no progress row → no badge", () => {
    expect(chapterBadge(undefined)).toBeNull();
  });
  it("completed → done (✓) wins over reading", () => {
    expect(chapterBadge({ completed: true, read_pct: 80 })).toBe("done");
  });
  it("partial read → reading (○)", () => {
    expect(chapterBadge({ completed: false, read_pct: 40 })).toBe("reading");
  });
  it("zero read, not completed → no badge", () => {
    expect(chapterBadge({ completed: false, read_pct: 0 })).toBeNull();
  });
});
