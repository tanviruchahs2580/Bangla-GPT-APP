import { useQuery } from "@tanstack/react-query";
import { get } from "../api";
import { Badge, Skeleton } from "../components/ui";
import { SchoolSections } from "../components/school/SchoolSections";
import { t } from "../i18n";
import type { SchoolHealth } from "../types";

/**
 * S3.2 school dashboard (school_admin / admin).
 * Summary aggregates only -- students/teachers/classes/sessions, learning
 * health buckets and a cross-class at-risk list. No chat content anywhere.
 */
export default function SchoolDashboard() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["school-overview"],
    queryFn: () => get<SchoolHealth>("/school/overview"),
  });

  if (isPending) {
    return (
      <main className="container" aria-live="polite">
        <p className="muted">{t("loading")}</p>
        <Skeleton w="60%" />
        <Skeleton w="40%" />
      </main>
    );
  }
  if (isError || !data) {
    return (
      <main className="container">
        <div className="card" role="alert">
          <h2>{t("errorGeneric")}</h2>
        </div>
      </main>
    );
  }

  return (
    <main className="container">
      <h1>{t("schoolDashboard")}</h1>
      <p className="muted">
        <span>{data.name}</span> ·{" "}
        <span>
          {t("sdCode")}: {data.code}
        </span>
      </p>

      <div className="stat-grid">
        <div className="stat">
          <span className="stat-value">{data.students}</span>
          <span className="stat-label">{t("students")}</span>
        </div>
        <div className="stat">
          <span className="stat-value">{data.teachers}</span>
          <span className="stat-label">{t("sdTeachers")}</span>
        </div>
        <div className="stat">
          <span className="stat-value">{data.classrooms}</span>
          <span className="stat-label">{t("classrooms")}</span>
        </div>
        <div className="stat">
          <span className="stat-value">{data.sessions_7d}</span>
          <span className="stat-label">{t("sdSessions")}</span>
        </div>
      </div>

      <section className="card" aria-label={t("sdHealthTitle")}>
        <h2>{t("sdHealthTitle")}</h2>
        <div className="stat-grid">
          <div className="stat">
            <span className="stat-value">{data.strong_pct}%</span>
            <span className="stat-label">
              {t("sdStrong")} ({data.strong})
            </span>
          </div>
          <div className="stat">
            <span className="stat-value">{data.support_pct}%</span>
            <span className="stat-label">
              {t("sdSupport")} ({data.support})
            </span>
          </div>
          <div className="stat">
            <span className="stat-value">{data.risk_pct}%</span>
            <span className="stat-label">
              {t("spRisk")} ({data.risk})
            </span>
          </div>
          <div className="stat">
            <span className="stat-value">{data.ungraded}</span>
            <span className="stat-label">{t("sdUngraded")}</span>
          </div>
        </div>
      </section>

      <section className="card" aria-label={t("sdAtRiskList")}>
        <h2>{t("sdAtRiskList")}</h2>
        {data.at_risk.length === 0 ? (
          <p className="muted">{t("sdEmpty")}</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("name")}</th>
                  <th>{t("classLabel")}</th>
                  <th>{t("wmAvg")}</th>
                  <th>{t("wmTrend")}</th>
                </tr>
              </thead>
              <tbody>
                {data.at_risk.map((r) => (
                  <tr key={r.student_id}>
                    <td>{r.name}</td>
                    <td>
                      {r.class_level} · {r.section}
                    </td>
                    <td>
                      <Badge tone="warn">{r.avg_score_pct ?? 0}%</Badge>
                    </td>
                    <td>{r.trend}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <SchoolSections />
    </main>
  );
}
