/**
 * F-119 residual: the confidence badge renders a heuristic blend of source
 * breadth and mean retrieval score (services/safety.answer_confidence), not a
 * calibrated probability. The audit's required wording is "retrieval
 * confidence (heuristic)" / "সোর্স-নিশ্চয়তা (আনুমানিক)" with the percentage
 * rendered against that label (docs/rag/architecture.md 6.7); before this the
 * copy read as a bare "x% confident" / "x% নিশ্চিত". These assertions fail if
 * either language loses the qualifier.
 */
import { afterEach, describe, expect, it } from "vitest";
import { setLang, t } from "../i18n";

describe("confidence badge names the heuristic (F-119)", () => {
  afterEach(() => setLang("bn"));

  it("keeps the Bangla qualifier and the percentage", () => {
    setLang("bn");
    const text = t("confidenceBadge", { pct: 87 });
    expect(text).toContain("৮৭%");
    expect(text).toContain("আনুমানিক");
    expect(text).not.toBe("৮৭% নিশ্চিত");
  });

  it("keeps the English qualifier and the percentage", () => {
    setLang("en");
    const text = t("confidenceBadge", { pct: 87 });
    expect(text).toBe("87% retrieval confidence (heuristic)");
    expect(text).not.toBe("87% confident");
  });
});
