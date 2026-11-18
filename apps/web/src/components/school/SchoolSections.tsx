import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { formatServerDateTime } from "../../lib/datetime";
import {
  getSchoolAnalytics,
  getSchoolClasses,
  getSchoolCoverage,
  getSchoolStudents,
  getSchoolTeachers,
} from "../../api";
import { Badge, Button, EmptyState, Skeleton, Spinner } from "../ui";
import { ResponsiveTable } from "../ResponsiveTable";
import { t } from "../../i18n";
import { track } from "../../lib/analytics";

/**
 * F-022: the five section queries used to render nothing at all until data
 * arrived, and nothing ever if the request failed — the school admin saw an
 * empty dashboard with no spinner, no error and no way to retry. Each
 * section now owns its pending/error state.
 */
function SectionState({
  label,
  q,
}: {
  label: string;
  q: UseQueryResult<unknown>;
}) {
  if (q.isPending) {
    return (
      <section className="card" aria-label={label}>
        <h2>{label}</h2>
        {/* E2: the section's own shape while it loads — table rows — with
            the loading state still announced (Spinner carries
            role="status"; the skeleton blocks are aria-hidden). */}
        <div className="stack">
          <Spinner />
          <Skeleton variant="row" />
          <Skeleton variant="row" />
          <Skeleton variant="row" />
        </div>
      </section>
    );
  }
  if (q.isError) {
    return (
      <section className="card" aria-label={label}>
        <h2>{label}</h2>
        <p className="error" role="alert">
          {t("errorGeneric")}
        </p>
        <Button variant="ghost" size="sm" onClick={() => void q.refetch()}>
          {t("retry")}
        </Button>
      </section>
    );
  }
  // Data is present: the caller renders the real section.
  return null;
}

/** school section: roster, teachers, classes, coverage, analytics. */
export function SchoolSections() {
  const students = useQuery({
    queryKey: ["school-students"],
    queryFn: () => getSchoolStudents(100, 0),
  });
  const teachers = useQuery({
    queryKey: ["school-teachers"],
    queryFn: getSchoolTeachers,
  });
  const classes = useQuery({
    queryKey: ["school-classes"],
    queryFn: getSchoolClasses,
  });
  const coverage = useQuery({
    queryKey: ["school-coverage"],
    queryFn: getSchoolCoverage,
  });
  const analytics = useQuery({
    queryKey: ["school-analytics"],
    queryFn: () => {
      track("report_viewed", { role: "school", period: "30d" });
      return getSchoolAnalytics(30);
    },
  });

  return (
    <>
      {students.data ? (
        <section className="card" aria-label={t("students")}>
          <h2>
            {t("students")} ({students.data.total})
          </h2>
          <ResponsiveTable
            columns={[
              { id: "name", header: t("name"), cell: (s) => s.name },
              {
                id: "class",
                header: t("classLabel"),
                cell: (s) => (
                  <>
                    {s.class_level} · {s.section}
                  </>
                ),
              },
              {
                id: "quizzes",
                header: t("secQuizzes"),
                cell: (s) => s.quiz_attempts,
              },
              {
                id: "last_active",
                header: t("secLastActive"),
                cellClassName: "muted",
                cell: (s) => formatServerDateTime(s.last_active) || "—",
              },
            ]}
            rows={students.data.items}
            rowKey={(s) => String(s.student_id)}
          />
        </section>
      ) : (
        <SectionState label={t("students")} q={students} />
      )}

      {teachers.data ? (
        <section className="card" aria-label={t("sdTeachers")}>
          <h2>{t("sdTeachers")}</h2>
          <ResponsiveTable
            columns={[
              { id: "name", header: t("name"), cell: (r) => r.name },
              {
                id: "subjects",
                header: t("subject"),
                cell: (r) => r.subjects.join(", ") || "—",
              },
              {
                id: "classrooms",
                header: t("classrooms"),
                cell: (r) => r.classrooms,
              },
            ]}
            rows={teachers.data}
            rowKey={(r) => String(r.teacher_id)}
          />
        </section>
      ) : (
        <SectionState label={t("sdTeachers")} q={teachers} />
      )}

      {classes.data ? (
        <section className="card" aria-label={t("classrooms")}>
          <h2>{t("classrooms")}</h2>
          <ResponsiveTable
            columns={[
              {
                id: "class",
                header: t("classLabel"),
                cell: (c) => c.class_level,
              },
              { id: "section", header: t("section"), cell: (c) => c.section },
              {
                id: "students",
                header: t("students"),
                cell: (c) => c.students,
              },
              {
                id: "quizzes",
                header: t("secQuizzes"),
                cell: (c) => (
                  <>
                    {c.attempts_graded}/{c.quiz_attempts}
                  </>
                ),
              },
              {
                id: "avg",
                header: t("wmAvg"),
                cell: (c) =>
                  c.avg_quiz_accuracy == null
                    ? "—"
                    : `${Math.round(c.avg_quiz_accuracy)}%`,
              },
            ]}
            rows={classes.data}
            rowKey={(c) => String(c.classroom_id)}
          />
        </section>
      ) : (
        <SectionState label={t("classrooms")} q={classes} />
      )}

      {coverage.data ? (
        <section className="card" aria-label={t("covTitle")}>
          <h2>{t("covTitle")}</h2>
          {coverage.data.rows.length === 0 ? (
            // E2: the shared empty state instead of a lone muted line.
            <EmptyState size="sm" icon={BookOpen} title={t("covEmpty")} />
          ) : (
            <ResponsiveTable
              columns={[
                {
                  id: "class",
                  header: t("classLabel"),
                  cell: (r) => r.class_level,
                },
                {
                  id: "content",
                  header: t("covContent"),
                  cell: (r) => r.content_subjects.join(", ") || "—",
                },
                {
                  id: "uncovered",
                  header: t("covUncovered"),
                  cell: (r) =>
                    r.uncovered_subjects.length === 0 ? (
                      <span className="muted">—</span>
                    ) : (
                      r.uncovered_subjects.map((s) => (
                        <Badge key={s} tone="warn">
                          {s}
                        </Badge>
                      ))
                    ),
                },
                {
                  id: "read",
                  header: t("reportChaptersRead"),
                  cell: (r) => (
                    <>
                      {r.chapters_read}/{r.chapters_available}
                    </>
                  ),
                },
                {
                  id: "completed",
                  header: t("covCompleted"),
                  cell: (r) => r.chapters_completed,
                },
              ]}
              rows={coverage.data.rows}
              rowKey={(r) => String(r.class_level)}
            />
          )}
        </section>
      ) : (
        <SectionState label={t("covTitle")} q={coverage} />
      )}

      {analytics.data ? (
        <section className="card" aria-label={t("anaTitle")}>
          <h2>{t("anaTitle")}</h2>
          <p className="muted m-0">{analytics.data.days}d</p>
          <div className="stat-grid">
            <div className="stat">
              <span className="stat-value">
                {Math.round(analytics.data.daily_active_avg)}
              </span>
              <span className="stat-label">{t("anaDaily")}</span>
            </div>
            <div className="stat">
              <span className="stat-value">
                {analytics.data.questions_asked}
              </span>
              <span className="stat-label">{t("reportQuestions")}</span>
            </div>
            <div className="stat">
              <span className="stat-value">{analytics.data.quiz_attempts}</span>
              <span className="stat-label">{t("secQuizzes")}</span>
            </div>
            <div className="stat">
              <span className="stat-value">
                {analytics.data.avg_quiz_score_pct == null
                  ? "—"
                  : `${Math.round(analytics.data.avg_quiz_score_pct)}%`}
              </span>
              <span className="stat-label">{t("avgScore")}</span>
            </div>
          </div>
        </section>
      ) : (
        <SectionState label={t("anaTitle")} q={analytics} />
      )}
    </>
  );
}
