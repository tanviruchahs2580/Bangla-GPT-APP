/** জিজ্ঞাসা tab: tutor scoped to this chapter via the chapter context chip. */
import { useId, useState } from "react";
import { post } from "../../../api";
import type { AskResponse } from "../../../types";
import { Card } from "../../../components/ui";
import { t } from "../../../i18n";
import { SafeMarkdownLazy as SafeMarkdown } from "../../../lib/safeMarkdownLazy";
import { getLowData } from "../../../lib/lowData";

export function ChapterAsk({
  subject,
  chapter,
  classLevel,
}: {
  subject: string;
  chapter: string;
  classLevel: number;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // FE-FIX (a11y): the input was placeholder-only, so the field had no label
  // for a screen reader (a placeholder is a hint, and it disappears on typing).
  const inputId = useId();

  const ask = async () => {
    const q = question.trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await post<AskResponse>("/tutor/ask", {
        question: q,
        class_level: classLevel,
        subject,
        chapter,
        low_data: getLowData(),
      });
      setAnswer(res);
      setQuestion("");
    } catch {
      setError(t("errorGeneric"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="row-flex ask-context-row">
        <span className="badge badge-teal">
          {t("contextChip")}: {chapter}
        </span>
      </div>
      <label className="visually-hidden" htmlFor={inputId}>
        {t("askAboutChapter")}
      </label>
      <div className="row-flex ask-row">
        <input
          id={inputId}
          className="input ask-input"
          value={question}
          placeholder={t("askAboutChapter")}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            // FE-FIX-013: an Android IME uses Enter to confirm a Bangla
            // composition; without this the half-composed question is asked.
            if (e.key === "Enter" && !e.nativeEvent.isComposing) void ask();
          }}
        />
        <button
          className="btn btn-primary"
          onClick={ask}
          disabled={busy || question.trim().length < 3}
        >
          {t("send")}
        </button>
      </div>
      {busy && (
        <p className="muted" role="status">
          {t("thinking")}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {answer && (
        // FE-FIX (a11y): the answer used to appear silently. The live
        // semantics sit on the answer itself rather than on a second,
        // visually-hidden copy of its text: one node, announced once, and the
        // DOM does not carry the same sentence twice — which also keeps
        // `getByText` unambiguous for every consumer (tests, e2e specs and any
        // future reader of this tree). A duplicate hidden node would announce
        // the same sentence the visible one already contains.
        <Card className="chapter-card" role="status" aria-live="polite">
          <div className="chips-gap">
            <span className={answer.grounded ? "badge badge-teal" : "badge"}>
              {answer.grounded ? t("supportedBadge") : t("unsupportedBadge")}
            </span>
          </div>
          <SafeMarkdown content={answer.answer} />
          {answer.sources.length > 0 && (
            <p className="muted muted-sm section-gap-top">
              {t("chapter")}: {answer.sources[0].chapter}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
