import { describe, expect, it } from "vitest";
import { chapterBadge, ttsSupported } from "../lib/progress";

describe("S1.2 chapter badge logic", () => {
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

describe("S1.2 TTS feature guard", () => {
  it("unsupported browser (no speechSynthesis) → false, no crash", () => {
    expect(ttsSupported({} as Window)).toBe(false);
    expect(ttsSupported(undefined)).toBe(false);
  });
  it("supported browser → true", () => {
    expect(ttsSupported({ speechSynthesis: {} } as Window)).toBe(true);
  });
});
