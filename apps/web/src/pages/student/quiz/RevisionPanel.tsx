import { Card } from "../../../components/ui";
import { t } from "../../../i18n";
import type { RevisionDue, RevisionItemOut } from "../../../types";

/** F-094 split: the spaced-revision tab body, extracted from QuizPage. */
export function RevisionPanel({
  due,
  busy,
  error,
  onAnswer,
}: {
  due: RevisionDue | undefined;
  busy: boolean;
  error: string | null;
  onAnswer: (item: RevisionItemOut, chosen: number) => void;
}) {
  return (
    <div className="stack">
      {due && due.items.length === 0 && (
        <Card>
          <p className="muted flush">{t("revisionEmpty")}</p>
        </Card>
      )}
      {due?.items.map((item) => (
        <Card key={item.id} className="row quiz-review-row">
          <div className="row-main">
            <div className="row-title">{item.question}</div>
            <div className="row-sub">
              {t("chapter")}: {item.chapter}
            </div>
            <div className="stack section-gap-top">
              {item.options.map((opt, oi) => (
                <button
                  key={oi}
                  className="quiz-option"
                  disabled={busy}
                  onClick={() => onAnswer(item, oi)}
                >
                  {opt}
                </button>
              ))}
              <p className="muted muted-sm flush">{t("revisionChoose")}</p>
            </div>
          </div>
        </Card>
      ))}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
