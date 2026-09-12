import { describe, expect, it } from "vitest";
import { SECTION, parseStructuredAnswer } from "../lib/structuredAnswer";

// Golden sample: same layout the API's SYSTEM_PROMPT (rule ৬) and mock provider emit.
const GOLDEN = [
  `[mock] ${SECTION.simple} কোষ হইছের জীবদেহের একক`,
  `${SECTION.example} চুণের গাঁথানির ইঁটের মতো`,
  `${SECTION.points}`,
  "- কোষের গুরুত্বপূর্ণ অংশগুলো",
  "- প্রতিটি অংশের কাজ আলাদা",
  `${SECTION.check} বুঝতে পারলি?`,
].join("\n");

describe("parseStructuredAnswer (S1.4)", () => {
  it("parses the golden sample into all four sections in order", () => {
    const r = parseStructuredAnswer(GOLDEN);
    expect(r.structured).toBe(true);
    expect(r.simple).toBe("কোষ হইছের জীবদেহের একক");
    expect(r.example).toBe("চুণের গাঁথানির ইঁটের মতো");
    expect(r.points).toEqual([
      "কোষের গুরুত্বপূর্ণ অংশগুলো",
      "প্রতিটি অংশের কাজ আলাদা",
    ]);
    expect(r.check).toBe("বুঝতে পারলি?");
    expect(r.preamble).toBe("[mock]");
  });

  it("returns structured:false for a plain refusal answer", () => {
    const r = parseStructuredAnswer(
      "উত্তরটি পাঠ্যবইয়ের বিষয়বস্তুর ভিত্তিতে দেওয়া সম্ভব না।",
    );
    expect(r.structured).toBe(false);
    expect(r.points).toEqual([]);
  });

  it("tolerates a missing single section (3-of-4 marks still parse)", () => {
    const partial = `${SECTION.simple} সহজ কথা\n${SECTION.points}\n- ক\n- খ\n${SECTION.check} বুঝলি?`;
    const r = parseStructuredAnswer(partial);
    expect(r.structured).toBe(true);
    expect(r.example).toBe("");
    expect(r.points).toEqual(["ক", "খ"]);
  });

  it("strips bullet markers of every kind", () => {
    const bullets = `${SECTION.simple} স\n${SECTION.example} উ\n${SECTION.points}\n• ত\n· থ\n${SECTION.check}?`;
    const r = parseStructuredAnswer(bullets);
    expect(r.points).toEqual(["ত", "থ"]);
  });
});
