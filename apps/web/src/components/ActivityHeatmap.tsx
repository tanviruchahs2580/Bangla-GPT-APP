import { t } from "../i18n";
import type { ActivitySummary } from "../types";

/**
 * The practice heatmap, shared by the student's own page (MePage) and the
 * parent's view of a child (ParentDashboard).
 *
 * FE-FIX (duplication): the grid markup, the level buckets and the totals
 * reducer were copy-pasted between the two pages — two places to fix the next
 * time the buckets or the accessible name change, and the parent's copy had
 * already drifted (no test id, its own identical reducer). One component now
 * owns the contract FE-11 established: the per-day counts live in a labelled
 * image equivalent a screen reader can announce, not only in `title`
 * tooltips.
 */
export function heatmapTotals(days: ActivitySummary["days"]): {
  questions: number;
  quizzes: number;
  active: number;
} {
  return days.reduce(
    (acc, d) => {
      acc.questions += d.questions;
      acc.quizzes += d.quizzes;
      if (d.questions + d.quizzes > 0) acc.active += 1;
      return acc;
    },
    { questions: 0, quizzes: 0, active: 0 },
  );
}

export function ActivityHeatmap({
  days,
  testId,
}: {
  days: ActivitySummary["days"];
  testId?: string;
}) {
  const totals = heatmapTotals(days);
  const gridLabel = t("heatmapSummary", {
    questions: totals.questions,
    active: totals.active,
    days: days.length,
  });
  return (
    <div
      className="heatmap"
      data-testid={testId}
      role="img"
      aria-label={gridLabel}
    >
      <span className="sr-only">{gridLabel}</span>
      {days.map((d) => {
        const total = d.questions + d.quizzes;
        const lvl = total === 0 ? 0 : total <= 2 ? 1 : total <= 5 ? 2 : 3;
        const title = [
          d.date,
          t(d.questions === 1 ? "activityQuestion" : "activityQuestions", {
            n: d.questions,
          }),
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
