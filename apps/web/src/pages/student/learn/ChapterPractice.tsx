/** অনুশীলন tab: mini quiz with the chapter preselected, no page exit. */
import { useState } from "react";
import { ArrowLeft, ArrowRight, Check, RotateCw, X } from "lucide-react";
import { post } from "../../../api";
import type { QuizResult, QuizStarted } from "../../../types";
import { useAuth } from "../../../AuthContext";
import { Card } from "../../../components/ui";
import { t } from "../../../i18n";
import { friendlyError } from "../../../errors";
import { QuizOptionGroup } from "../../../components/QuizOptionGroup";

export function ChapterPractice({
  subject,
  chapter,
  classLevel,
}: {
  subject: string;
  chapter: string;
  classLevel: number;
}) {
  const { me } = useAuth();
  const [started, setStarted] = useState<QuizStarted | null>(null);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [current, setCurrent] = useState(0);
  const [result, setResult] = useState<QuizResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await post<QuizStarted>("/quizzes", {
        student_id: me?.profile_id,
        class_level: classLevel,
        subject,
        chapter,
        num_questions: 5,
      });
      setStarted(res);
      setAnswers({});
      setCurrent(0);
      setResult(null);
    } catch (e) {
      // F-110: the branch used to print the API's raw English detail.message
      // ("Curriculum index unavailable") into this Bangla screen. Every other
      // surface maps the machine code through friendlyError; do the same here
      // (index_unavailable has retryable copy).
      setError(friendlyError((e as { rawDetail?: unknown }).rawDetail).text);
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!started) return;
    setBusy(true);
    try {
      const res = await post<QuizResult>(
        `/quizzes/${started.attempt_id}/submit`,
        {
          answers: started.questions.map((_, i) => answers[i] ?? -1),
        },
      );
      setResult(res);
      setStarted(null);
    } catch {
      setError(t("errorGeneric"));
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <div className="stack">
        <div className="center">
          <div className="stat-value">{Math.round(result.score_pct)}%</div>
          <div className="muted">
            {t("correctOutOf", {
              correct: result.correct,
              total: result.total,
            })}
          </div>
        </div>
        {result.review.map((r, i) => (
          <Card key={i} className="quiz-review-row">
            <div className="row-title">{r.question_text}</div>
            <div className="row-sub row-flex">
              {r.is_correct ? (
                <Check size={14} aria-hidden />
              ) : (
                <>
                  <X size={14} aria-hidden /> —{" "}
                  {r.options[r.correct_index] ?? ""}
                </>
              )}
            </div>
          </Card>
        ))}
        <button className="btn btn-soft" onClick={start} disabled={busy}>
          {t("startQuiz")} <RotateCw size={15} aria-hidden />
        </button>
      </div>
    );
  }

  if (started) {
    const q = started.questions[current];
    const chosen = answers[current];
    return (
      <div className="stack">
        <div className="row-flex">
          <span className="badge">
            {current + 1}/{started.questions.length}
          </span>
          <span className="muted muted-sm">{chapter}</span>
        </div>
        <div className="row-title quiz-q-title">{q.question_text}</div>
        {/* Same component as the quiz page: the tab used to announce
            role="radio" with every option in the tab order and no arrow keys,
            which is the defect QuizPage was fixed for. */}
        <QuizOptionGroup
          options={q.options}
          chosen={chosen}
          label={q.question_text}
          onChoose={(oi) => setAnswers((a) => ({ ...a, [current]: oi }))}
        />
        <div className="row-flex quiz-pager">
          <button
            className="btn btn-ghost btn-sm"
            disabled={current === 0}
            onClick={() => setCurrent((c) => c - 1)}
          >
            <ArrowLeft size={15} aria-hidden /> {t("previousQuestion")}
          </button>
          {current < started.questions.length - 1 ? (
            <button
              className="btn btn-primary btn-sm"
              onClick={() => setCurrent((c) => c + 1)}
            >
              {t("nextQuestion")} <ArrowRight size={15} aria-hidden />
            </button>
          ) : (
            <button
              className="btn btn-teal btn-sm"
              onClick={submit}
              disabled={busy}
            >
              {t("finishQuiz")}
            </button>
          )}
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    );
  }

  return (
    <div className="stack center">
      <p className="muted">
        {t("practiceThisChapter")} — {chapter}
      </p>
      <button
        className="btn btn-primary"
        onClick={start}
        disabled={busy || !me?.profile_id}
      >
        {t("startQuiz")}
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
