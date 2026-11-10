import { Button, Card, Stat } from "../../../components/ui";
import { formatNumber, t } from "../../../i18n";
import { subjectOptions } from "../../../lib/subjectOptions";
import type { StudentProgress } from "../../../types";

/** F-094 split: the quiz-tab start card, extracted from QuizPage. */

export function StartQuizCard({
  number,
  subject,
  onNumberChange,
  onSubjectChange,
  progress,
  error,
  busy,
  canStart,
  onStart,
}: {
  number: string;
  subject: string;
  onNumberChange: (value: string) => void;
  onSubjectChange: (value: string) => void;
  progress: StudentProgress | undefined;
  error: string | null;
  busy: boolean;
  canStart: boolean;
  onStart: () => void;
}) {
  const avg = progress?.avg_score_pct;
  return (
    <Card>
      <div className="card-title">{t("startQuiz")}</div>
      <div className="field">
        <label htmlFor="qcount">{t("questionCount")}</label>
        <select
          id="qcount"
          className="select"
          value={number}
          onChange={(e) => onNumberChange(e.target.value)}
        >
          {[3, 5, 10, 15].map((n) => (
            <option key={n} value={n}>
              {formatNumber(n)}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="quiz-subject">{t("subject")}</label>
        <select
          id="quiz-subject"
          className="select"
          value={subject}
          onChange={(e) => onSubjectChange(e.target.value)}
        >
          {subjectOptions().map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      {progress && progress.attempts_graded > 0 && (
        <div className="stat-grid section-gap-top">
          {/* A graded quiz with no average is not an average of 0: the API
              returns null for "nothing measured yet" (the same rule the school
              table and the student report follow). */}
          <Stat
            value={
              avg == null
                ? t("notAvailable")
                : `${formatNumber(Math.round(avg))}%`
            }
            label={t("avgScore")}
          />
          <Stat
            value={formatNumber(progress.attempts_graded)}
            label={t("gradedQuizzes")}
          />
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <Button
        variant="primary"
        block
        onClick={onStart}
        disabled={busy || !canStart}
      >
        {t("startQuiz")}
      </Button>
      {!canStart && (
        <p className="muted muted-sm section-gap-top">{t("notStarted")}</p>
      )}
    </Card>
  );
}
