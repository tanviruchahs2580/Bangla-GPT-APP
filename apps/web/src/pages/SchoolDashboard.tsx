import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { get } from "../api";
import { Badge, EmptyState, Skeleton, Spinner } from "../components/ui";
import { ResponsiveTable } from "../components/ResponsiveTable";
import { SchoolSections } from "../components/school/SchoolSections";
import { formatNumber, t } from "../i18n";
import type { SchoolHealth } from "../types";

/**
 * school dashboard (school_admin / admin).
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
      <main
        id="main-content"
        tabIndex={-1}
        className="container"
        aria-live="polite"
      >
        {/* E2: the page's real shape while it loads — the four summary
            stats, the health card, then the at-risk table — instead of a
            sentence beside two unshaped bars. Spinner keeps the loading
            state announced (the skeleton blocks are aria-hidden). */}
        <Spinner />
        <div className="stat-grid">
          <Skeleton variant="card" h={72} />
          <Skeleton variant="card" h={72} />
          <Skeleton variant="card" h={72} />
          <Skeleton variant="card" h={72} />
        </div>
        <Skeleton variant="card" h={140} />
        <Skeleton variant="row" />
        <Skeleton variant="row" />
        <Skeleton variant="row" />
      </main>
    );
  }
  if (isError || !data) {
    return (
      <main id="main-content" tabIndex={-1} className="container">
        <div className="card" role="alert">
          <h2>{t("errorGeneric")}</h2>
        </div>
      </main>
    );
  }

  return (
    <main id="main-content" tabIndex={-1} className="container">
      <h1>{t("schoolDashboard")}</h1>
      <p className="muted">
        <span>{data.name}</span> ·{" "}
        <span>
          {t("sdCode")}: {data.code}
        </span>
      </p>

      <div className="stat-grid">
        <div className="stat">
          <span className="stat-value">{formatNumber(data.students)}</span>
          <span className="stat-label">{t("students")}</span>
        </div>
        <div className="stat">
          <span className="stat-value">{formatNumber(data.teachers)}</span>
          <span className="stat-label">{t("sdTeachers")}</span>
        </div>
        <div className="stat">
          <span className="stat-value">{formatNumber(data.classrooms)}</span>
          <span className="stat-label">{t("classrooms")}</span>
        </div>
        <div className="stat">
          <span className="stat-value">{formatNumber(data.sessions_7d)}</span>
          <span className="stat-label">{t("sdSessions")}</span>
        </div>
      </div>

      <section className="card" aria-label={t("sdHealthTitle")}>
        <h2>{t("sdHealthTitle")}</h2>
        <div className="stat-grid">
          <div className="stat">
            <span className="stat-value">{formatNumber(data.strong_pct)}%</span>
            <span className="stat-label">
              {t("sdStrong")} ({formatNumber(data.strong)})
            </span>
          </div>
          <div className="stat">
            <span className="stat-value">
              {formatNumber(data.support_pct)}%
            </span>
            <span className="stat-label">
              {t("sdSupport")} ({formatNumber(data.support)})
            </span>
          </div>
          <div className="stat">
            <span className="stat-value">{formatNumber(data.risk_pct)}%</span>
            <span className="stat-label">
              {t("spRisk")} ({formatNumber(data.risk)})
            </span>
          </div>
          <div className="stat">
            <span className="stat-value">{formatNumber(data.ungraded)}</span>
            <span className="stat-label">{t("sdUngraded")}</span>
          </div>
        </div>
      </section>

      <section className="card" aria-label={t("sdAtRiskList")}>
        <h2>{t("sdAtRiskList")}</h2>
        {data.at_risk.length === 0 ? (
          // E2: an empty at-risk list is good news — said with the shared
          // empty state instead of a lone muted line.
          <EmptyState size="sm" icon={ShieldCheck} title={t("sdEmpty")} />
        ) : (
          <ResponsiveTable
            columns={[
              { id: "name", header: t("name"), cell: (r) => r.name },
              {
                id: "class",
                header: t("classLabel"),
                cell: (r) => (
                  <>
                    {r.class_level} · {r.section}
                  </>
                ),
              },
              {
                id: "avg",
                header: t("wmAvg"),
                cell: (r) => {
                  /* FE-FIX-006: `avg_score_pct` is `number | null` on
                      purpose (api.ts SchoolAtRiskRow) — null means "nothing
                      graded yet", not "scored zero". Coercing it to 0 made
                      a warning badge claim a measurement the API never
                      took, which is exactly the kind of number a school
                      admin would act on. */
                  return r.avg_score_pct == null ? (
                    <Badge>{t("notAvailable")}</Badge>
                  ) : (
                    <Badge tone="warn">{`${formatNumber(r.avg_score_pct)}%`}</Badge>
                  );
                },
              },
              { id: "trend", header: t("wmTrend"), cell: (r) => r.trend },
            ]}
            rows={data.at_risk}
            rowKey={(r) => String(r.student_id)}
          />
        )}
      </section>

      <SchoolSections />
    </main>
  );
}
