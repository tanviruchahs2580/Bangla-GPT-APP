import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { formatNumber, setLang, t, toBanglaDigits } from "../i18n";

// F-113: the numeral policy (docs/glossary-bn.md) is applied at the t()
// interpolation boundary. Static copy already used Bangla digits while every
// interpolated count was rendered Latin by String(v), so "মিনি কুইজ (৩টি
// প্রশ্ন)" sat next to "5টি প্রশ্ন" on the same screen. These tests pin the
// rule: a value that is entirely a number is a quantity and takes the
// language's digits; every other value (names, codes, dates) is opaque text.
describe("numeral policy at the interpolation boundary", () => {
  beforeEach(() => setLang("bn"));
  afterEach(() => setLang("bn"));

  it("renders numeric quantities in Bangla digits under bn", () => {
    expect(t("activityQuestions", { n: 5 })).toBe("৫টি প্রশ্ন");
    expect(t("correctOutOf", { correct: 8, total: 10 })).toBe("৮/১০ সঠিক");
    expect(t("confidenceBadge", { pct: 87 })).toBe(
      "৮৭% সোর্স-নিশ্চয়তা (আনুমানিক)",
    );
    expect(t("streakLabel", { days: 3 })).toBe("৩ দিনের ধারাবাহিকতা");
    expect(t("spWeek", { n: 2 })).toBe("সপ্তাহ ২");
  });

  it("converts digit strings a caller assembled, groups like bn-BD", () => {
    // The report path passes the percentage as a string (lib/text.ts).
    expect(t("sugg_keep_momentum", { avg_score_pct: "88" })).toBe(
      "দারুণ অগ্রগতি! গড় স্কোর ৮৮% — এই গতি ধরে রাখুন।",
    );
    // A digit string is translated digit-for-digit and never regrouped: a
    // year or a code must not become "২,০২৬" on its way to the screen.
    expect(t("activityQuestions", { n: "1200" })).toBe("১২০০টি প্রশ্ন");
    expect(t("activityQuestions", { n: 1200 })).toBe("১,২০০টি প্রশ্ন");
  });

  it("keeps ids and mixed strings in Latin digits", () => {
    expect(t("assigned", { id: 42 })).toBe("অ্যাসাইন হয়েছে (চেষ্টা #42)");
    // A name, a code or a pre-formatted timestamp is opaque text.
    expect(t("thGreeting", { name: "শিক্ষার্থী 7" })).toBe(
      "স্বাগতম, শিক্ষার্থী 7",
    );
    expect(t("statusChecked", { when: "2026-10-20 10:30" })).toBe(
      "সর্বশেষ যাচাই: 2026-10-20 10:30",
    );
  });

  it("renders Latin digits with en grouping under en", () => {
    setLang("en");
    expect(t("activityQuestions", { n: 5 })).toBe("5 questions");
    expect(t("activityQuestions", { n: 1200 })).toBe("1,200 questions");
    // English never gets Bangla digits even if a caller sends a digit string.
    expect(t("sugg_keep_momentum", { avg_score_pct: "88" })).toBe(
      "Great progress! Average score 88% — keep up the momentum.",
    );
  });

  it("formatNumber follows the active language and toBanglaDigits is exact", () => {
    expect(formatNumber(1234, "bn")).toBe("১,২৩৪");
    expect(formatNumber(1234, "en")).toBe("1,234");
    expect(formatNumber(5.5, "bn")).toBe("৫.৫");
    expect(toBanglaDigits("১৮০ দিন, 100%")).toBe("১৮০ দিন, ১০০%");
    expect(toBanglaDigits("no digits")).toBe("no digits");
  });
});

// F-109: English counted sentences read "1 questions" because the dictionary
// had no singular form. t() selects one through Intl.PluralRules when the
// sentence carries exactly one numeric placeholder; Bangla has no number
// agreement, so the Bangla sentence is unchanged at every count.
describe("English counted nouns", () => {
  beforeEach(() => setLang("en"));
  afterEach(() => setLang("bn"));

  it("uses the singular sentence at exactly one", () => {
    expect(t("stAssigned", { n: 1 })).toBe("Assigned to 1 student");
    expect(t("stAssigned", { n: 2 })).toBe("Assigned to 2 students");
    expect(t("activityQuizzes", { n: 1 })).toBe("1 quiz");
    expect(t("activityMinutes", { n: 1 })).toBe("1 minute");
    expect(
      t("notifQuizAssigned", { count: 1, subject: "Science", chapter: "1" }),
    ).toBe("Quiz assigned: 1 question · Science · 1");
    expect(t("notifSupportPlan", { focus: 1 })).toBe(
      "A new support plan is ready (1 focus point)",
    );
    expect(t("thInsightRisk", { n: 1 })).toBe(
      "1 student is at risk — consider creating support plans.",
    );
    expect(t("anaCiRisk", { n: 1 })).toBe(
      "1 student at risk — create support plans.",
    );
    expect(t("genSourcesCount", { n: 1 })).toBe(
      "Grounded in 1 textbook source",
    );
    expect(t("quizUnansweredConfirm", { n: 1 })).toBe(
      "1 question has no answer yet. Submit with what you have?",
    );
  });

  it("pluralises through Intl.PluralRules categories, not a literal check", () => {
    // 1.0 selects "one" in CLDR; 0 and fractions select "other".
    expect(t("activityMinutes", { n: 1.0 })).toBe("1 minute");
    expect(t("activityMinutes", { n: 0 })).toBe("0 minutes");
    expect(t("activityMinutes", { n: 1.5 })).toBe("1.5 minutes");
  });

  it("leaves two-count sentences count-agnostic", () => {
    // heatmapSummary carries three counts; no single singular form exists,
    // so the sentence is written as label:value pairs that read at 1.
    expect(t("heatmapSummary", { days: 1, questions: 1, active: 1 })).toBe(
      "Practice summary — questions and quizzes: 1; active days: 1 of 1",
    );
  });

  it("keeps the Bangla sentence identical at one and many", () => {
    setLang("bn");
    expect(t("activityMinutes", { n: 1 })).toBe("১ মিনিট");
    expect(t("activityMinutes", { n: 9 })).toBe("৯ মিনিট");
    expect(t("stAssigned", { n: 1 }).replace("১", "N")).toBe(
      t("stAssigned", { n: 2 }).replace("২", "N"),
    );
  });
});
