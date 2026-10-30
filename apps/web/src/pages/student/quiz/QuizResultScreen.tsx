import { useEffect } from "react";
import { Check, ClipboardCheck, RefreshCcw } from "lucide-react";
import { Button, Card, ProgressRing } from "../../../components/ui";
import { t } from "../../../i18n";
import { cn } from "../../../lib/cn";
import { celebrate } from "../../../lib/confetti";
import type { QuizResult } from "../../../types";
import { ReteachCards } from "./ReteachCards";

/**
 * F-094 split: the result screen, extracted from QuizPage. Behaviour is
 * unchanged -- the page still owns the result state, the tutor explain
 * navigation and the restart action; this component renders them.
 */

function QuizCelebration({ score }: { score: number }) {
  useEffect(() => {
    celebrate(score);
  }, [score]);
  return null;
}

/** One wrong-answer row's explain payload type (see lib/quizExplain). */
type ReviewRow = QuizResult["review"][number];

export function QuizResultScreen({
  result,
  onExplain,
  onRestart,
}: {
  result: QuizResult;
  onExplain: (row: ReviewRow) => void;
  onRestart: () => void;
}) {
  return (
    <main id="main-content" tabIndex={-1} className="shell-main">
      <section className="section-head">
        <h1>{t("yourQuizResult")}</h1>
      </section>
      <QuizCelebration score={result.score_pct} />
      <Card className="card-featured">
        <div className="row-flex quiz-result-hero">
          <ProgressRing
            value={result.score_pct}
            size={120}
            label={<strong>{Math.round(result.score_pct)}%</strong>}
          />
          <div className="stat-value quiz-result-score">
            {t("correctOutOf", {
              correct: result.correct,
              total: result.total,
            })}
          </div>
        </div>
        <div className="stack section-gap-top">
          {result.review.map((r, i) => (
            <Card key={i} className="row quiz-review-row">
              <span
                className={cn(
                  "quick-icon",
                  r.is_correct ? "tile-ok" : "tile-danger",
                )}
              >
                {r.is_correct ? (
                  <Check size={18} aria-hidden />
                ) : (
                  <ClipboardCheck size={18} aria-hidden />
                )}
              </span>
              <div className="row-main">
                <div className="row-title">{r.question_text}</div>
                <div className="row-sub">
                  {t("chapter")}: {r.chapter} —{" "}
                  {r.options[r.correct_index] ?? ""}
                </div>
                {!r.is_correct && (
                  // wrong item → explain loop with full quiz context.
                  <Button
                    variant="ghost"
                    size="sm"
                    className="section-gap-top"
                    onClick={() => onExplain(r)}
                  >
                    {t("explainThis")}
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      </Card>
      {result.reteach && result.reteach.length > 0 && (
        <div className="section-gap-top">
          <ReteachCards cards={result.reteach} />
        </div>
      )}
      {/* one clear next step; everything else is secondary */}
      <div className="section-gap-top">
        <Button variant="primary" block onClick={onRestart}>
          <RefreshCcw size={18} aria-hidden /> {t("startQuiz")}
        </Button>
      </div>
    </main>
  );
}
