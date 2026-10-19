import { t } from "../i18n";

export interface ActivityDay {
  date: string;
  questions: number;
  quizzes: number;
  minutes: number;
}

/**
 * The activity heat grid (one cell per day, four levels).
 *
 * Extracted from the student profile and the parent dashboard: the two copies
 * were identical including the level thresholds, so a change to what counts as
 * a "busy" day would have had to be made twice and could silently diverge
 * between what a student sees about themselves and what a parent sees.
 *
 * The accessible name carries the streak (G-20: the same plural message the
 * visible label uses, so the announcement matches the page).
 */
export function HeatGrid({
  days,
  streak,
  testId,
}: {
  days: ActivityDay[];
  streak: number;
  testId?: string;
}) {
  return (
    <div
      className="heatmap"
      data-testid={testId}
      aria-label={t("streakLabel", { days: streak })}
    >
      {days.map((d) => {
        const total = d.questions + d.quizzes;
        const lvl = total === 0 ? 0 : total <= 2 ? 1 : total <= 5 ? 2 : 3;
        const title = [
          d.date,
          // G-20: one plural message, not a key chosen by the component.
          t("activityQuestions", { n: d.questions }),
          t("activityQuizzes", { n: d.quizzes }),
          t("activityMinutes", { n: d.minutes }),
        ].join(" · ");
        return (
          <span key={d.date} className={`heat-cell lvl-${lvl}`} title={title} />
        );
      })}
    </div>
  );
}

export default HeatGrid;
