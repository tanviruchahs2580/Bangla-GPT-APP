import { useQuery } from "@tanstack/react-query";
import {
  getSchoolAnalytics,
  getSchoolClasses,
  getSchoolCoverage,
  getSchoolStudents,
  getSchoolTeachers,
} from "../../api";
import { Badge } from "../ui";
import { t } from "../../i18n";
import { track } from "../../lib/analytics";

/** Wave 2 school section: roster, teachers, classes, coverage, analytics. */
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
      {students.data && (
        <section className="card" aria-label={t("students")}>
          <h2>
            {t("students")} ({students.data.total})
          </h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("name")}</th>
                  <th>{t("classLabel")}</th>
                  <th>{t("secQuizzes")}</th>
                  <th>{t("secLastActive")}</th>
                </tr>
              </thead>
              <tbody>
                {students.data.items.map((s) => (
                  <tr key={s.student_id}>
                    <td>{s.name}</td>
                    <td>
                      {s.class_level} · {s.section}
                    </td>
                    <td>{s.quiz_attempts}</td>
                    <td className="muted">{s.last_active ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {teachers.data && (
        <section className="card" aria-label={t("sdTeachers")}>
          <h2>{t("sdTeachers")}</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("name")}</th>
                  <th>{t("subject")}</th>
                  <th>{t("classrooms")}</th>
                </tr>
              </thead>
              <tbody>
                {teachers.data.map((r) => (
                  <tr key={r.teacher_id}>
                    <td>{r.name}</td>
                    <td>{r.subjects.join(", ") || "—"}</td>
                    <td>{r.classrooms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {classes.data && (
        <section className="card" aria-label={t("classrooms")}>
          <h2>{t("classrooms")}</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("classLabel")}</th>
                  <th>{t("section")}</th>
                  <th>{t("students")}</th>
                  <th>{t("secQuizzes")}</th>
                  <th>{t("wmAvg")}</th>
                </tr>
              </thead>
              <tbody>
                {classes.data.map((c) => (
                  <tr key={c.classroom_id}>
                    <td>{c.class_level}</td>
                    <td>{c.section}</td>
                    <td>{c.students}</td>
                    <td>
                      {c.attempts_graded}/{c.quiz_attempts}
                    </td>
                    <td>
                      {c.avg_quiz_accuracy == null
                        ? "—"
                        : `${Math.round(c.avg_quiz_accuracy)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {coverage.data && (
        <section className="card" aria-label={t("covTitle")}>
          <h2>{t("covTitle")}</h2>
          {coverage.data.rows.length === 0 ? (
            <p className="muted">{t("covEmpty")}</p>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>{t("classLabel")}</th>
                    <th>{t("covContent")}</th>
                    <th>{t("covUncovered")}</th>
                    <th>{t("reportChaptersRead")}</th>
                    <th>{t("covCompleted")}</th>
                  </tr>
                </thead>
                <tbody>
                  {coverage.data.rows.map((r) => (
                    <tr key={r.class_level}>
                      <td>{r.class_level}</td>
                      <td>{r.content_subjects.join(", ") || "—"}</td>
                      <td>
                        {r.uncovered_subjects.length === 0 ? (
                          <span className="muted">—</span>
                        ) : (
                          r.uncovered_subjects.map((s) => (
                            <Badge key={s} tone="warn">
                              {s}
                            </Badge>
                          ))
                        )}
                      </td>
                      <td>
                        {r.chapters_read}/{r.chapters_available}
                      </td>
                      <td>{r.chapters_completed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {analytics.data && (
        <section className="card" aria-label={t("anaTitle")}>
          <h2>{t("anaTitle")}</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            {analytics.data.days}d
          </p>
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
      )}
    </>
  );
}
