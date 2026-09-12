import { describe, expect, it } from "vitest";
import { buildExplainPayload, explainMessage } from "../lib/quizExplain";
import type { QuizExplainPayload } from "../lib/quizExplain";
import type { ReviewItem } from "../types";

const ITEM: ReviewItem = {
  question_text: "Which unit measures length?",
  options: ["Second", "Metre", "Litre", "Gram"],
  chosen: 3,
  correct_index: 1,
  is_correct: false,
  chapter: "Measurement-Chapter",
};

describe("S1.7 quiz explain payload", () => {
  it("buildExplainPayload carries the full quiz context", () => {
    const p = buildExplainPayload(ITEM);
    expect(p).toEqual({
      question: ITEM.question_text,
      options: ITEM.options,
      correct_index: ITEM.correct_index,
      user_answer: ITEM.chosen,
      chapter: ITEM.chapter,
    });
  });

  it("explainMessage embeds question, chapter, both answers and all options", () => {
    const msg = explainMessage(buildExplainPayload(ITEM));
    expect(msg).toContain("Which unit measures length?");
    expect(msg).toContain("Measurement-Chapter");
    // chosen answer and correct answer both labelled
    expect(msg).toContain("Gram");
    expect(msg).toContain("Metre");
    // every option is listed (chosen/correct additionally repeat on the answer lines)
    for (const opt of ITEM.options) {
      expect(msg).toContain(opt);
    }
    expect(msg.split("Second").length - 1).toBe(1); // non-answer options appear exactly once
    expect(msg.split("Metre").length - 1).toBe(2); // options list + correct-answer line
    expect(msg.split("Gram").length - 1).toBe(2); // options list + my-answer line
  });

  it("unanswered item is labelled as no answer", () => {
    const p: QuizExplainPayload = {
      ...buildExplainPayload(ITEM),
      user_answer: -1,
    };
    const msg = explainMessage(p);
    // the chosen option must NOT be claimed as the student's answer
    const answerLine = msg.split("\n").find((l) => l.startsWith("আমার উত্তর:"));
    expect(answerLine).toBeDefined();
    expect(answerLine).not.toContain("Gram");
  });
});
