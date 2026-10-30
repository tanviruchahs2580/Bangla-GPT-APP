import { ArrowLeft, ArrowRight } from "lucide-react";
import { Badge, Button, Card, ProgressRing } from "../../../components/ui";
import { QuizOptionGroup } from "../../../components/QuizOptionGroup";
import { t } from "../../../i18n";
import type { QuizStarted } from "../../../types";
import { ReteachCards } from "./ReteachCards";

/**
 * F-094 split: the in-progress quiz view, extracted from QuizPage. The page
 * still owns the answers, the current index, the submit guard and the draft
 * persistence; this component is the view plus its callbacks.
 */
export function QuizRunner({
  started,
  current,
  answers,
  busy,
  error,
  confirmSubmit,
  unanswered,
  onChoose,
  onPrevious,
  onNext,
  onRequestSubmit,
  onSubmitAnyway,
  onKeepAnswering,
}: {
  started: QuizStarted;
  current: number;
  answers: Record<number, number>;
  busy: boolean;
  error: string | null;
  confirmSubmit: boolean;
  unanswered: number;
  onChoose: (optionIndex: number) => void;
  onPrevious: () => void;
  onNext: () => void;
  onRequestSubmit: () => void;
  onSubmitAnyway: () => void;
  onKeepAnswering: () => void;
}) {
  const q = started.questions[current];
  // undefined before any option is picked; normalised here so the roving
  // tab stop and the arrow handler agree on "no choice yet".
  const chosen = answers[current] ?? null;
  const answeredCount = Object.keys(answers).length;
  return (
    <main id="main-content" tabIndex={-1} className="shell-main">
      <section className="section-head">
        <h1>{t("practiceTitle")}</h1>
        <Badge>
          {current + 1}/{started.questions.length}
        </Badge>
      </section>
      {started.reteach && started.reteach.length > 0 && current === 0 && (
        <div className="stack chips-gap">
          <ReteachCards cards={started.reteach} />
        </div>
      )}
      <Card key={current} className="quiz-q">
        <div className="row-flex chips-gap">
          <ProgressRing
            value={(answeredCount / started.questions.length) * 100}
            size={64}
            label={
              <strong>
                {answeredCount}/{started.questions.length}
              </strong>
            }
          />
          <div className="row-main">
            <div className="row-title quiz-q-title">{q.question_text}</div>
            <div className="muted muted-sm">{t("chooseAnswers")}</div>
          </div>
        </div>
        <QuizOptionGroup
          options={q.options}
          chosen={chosen}
          label={q.question_text}
          onChoose={onChoose}
        />
        <div className="row-flex quiz-pager">
          <Button
            variant="ghost"
            size="sm"
            disabled={current === 0}
            onClick={onPrevious}
          >
            <ArrowLeft size={16} aria-hidden /> {t("previousQuestion")}
          </Button>
          {current < started.questions.length - 1 ? (
            <Button variant="primary" size="sm" onClick={onNext}>
              {t("nextQuestion")} <ArrowRight size={16} aria-hidden />
            </Button>
          ) : (
            <Button
              variant="teal"
              size="sm"
              onClick={onRequestSubmit}
              disabled={busy}
            >
              {t("finishQuiz")}
            </Button>
          )}
        </div>
        {error && (
          <p className="error section-gap-top" role="alert">
            {error}
          </p>
        )}
        {confirmSubmit && unanswered > 0 && (
          <div className="warn-strip section-gap-top" role="alert">
            <p>{t("quizUnansweredConfirm", { n: unanswered })}</p>
            <div className="row-flex">
              <Button
                variant="teal"
                size="sm"
                loading={busy}
                onClick={onSubmitAnyway}
              >
                {t("quizSubmitAnyway")}
              </Button>
              <Button variant="ghost" size="sm" onClick={onKeepAnswering}>
                {t("quizKeepAnswering")}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </main>
  );
}
