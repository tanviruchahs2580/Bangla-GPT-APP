/** জিজ্ঞাসা tab: tutor scoped to this chapter via the chapter context chip. */
import { useState } from "react";
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
      <div className="row-flex ask-row">
        <input
          className="input ask-input"
          value={question}
          placeholder={t("askAboutChapter")}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void ask();
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
      {busy && <p className="muted">{t("thinking")}</p>}
      {error && <p className="error">{error}</p>}
      {answer && (
        <Card className="chapter-card">
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
