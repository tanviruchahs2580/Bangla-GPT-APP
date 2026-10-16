import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { get, getParentReport, post } from "../api";
import { friendlyError } from "../errors";
import { t } from "../i18n";
import { track } from "../lib/analytics";
import { suggestionSentence } from "../lib/text";
import type { ActivitySummary, StudentBrief, StudentProgress } from "../types";

/**
 * F-024: switching the selected child used to keep rendering the previous
 * child's name and scores until the new request resolved (the old data was
 * only cleared when the selection became null), and a failed fetch silently
 * removed the whole card. Each child section now shows its own loading or
 * retryable error state instead of stale or absent data.
 */
function ChildSectionState({
  title,
  pending,
  failed,
  onRetry,
}: {
  title: string;
  pending: boolean;
  failed: boolean;
  onRetry: () => void;
}) {
  if (!pending && !failed) return null;
  return (
    <section className="card" aria-label={title}>
      <h2>{title}</h2>
      {pending ? (
        <p className="muted" role="status">
          {t("loading")}
        </p>
      ) : (
        <>
          <p className="error" role="alert">
            {t("errorGeneric")}
          </p>
          <button className="btn btn-sm btn-ghost" onClick={onRetry}>
            {t("retry")}
          </button>
        </>
      )}
    </section>
  );
}

export default function ParentDashboard() {
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [period, setPeriod] = useState<"weekly" | "monthly">("weekly");

  const childrenQuery = useQuery({
    queryKey: ["parent-children"],
    queryFn: () => get<StudentBrief[]>("/parents/me/children"),
  });
  const children = childrenQuery.data ?? [];

  // Per-child query keys: child B never renders under child A's data.
  const progressQuery = useQuery({
    queryKey: ["parent-progress", selected],
    queryFn: () =>
      get<StudentProgress>(`/parents/me/children/${selected}/progress`),
    enabled: selected !== null,
  });
  const activityQuery = useQuery({
    queryKey: ["parent-activity", selected],
    queryFn: () =>
      get<ActivitySummary>(`/parents/me/children/${selected}/activity`),
    enabled: selected !== null,
  });
  const reportQuery = useQuery({
    queryKey: ["parent-report", selected, period],
    queryFn: async () => {
      const r = await getParentReport(selected as number, period);
      track("report_viewed", { role: "parent", period });
      return r;
    },
    enabled: selected !== null,
  });
  const progress = progressQuery.data ?? null;
  const activity = activityQuery.data ?? null;
  const report = reportQuery.data ?? null;
  const selectedChild = children.find((c) => c.student_id === selected) ?? null;
  const childrenError =
    error ??
    (childrenQuery.isError
      ? (friendlyError(childrenQuery.error)?.text ?? t("errorGeneric"))
      : null);

  async function link(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      // C17: single-use invite code issued by the child — no bare IDs.
      await post("/parents/link/invite", { code: code.trim().toUpperCase() });
      setMessage(t("parentLinkOk"));
      setCode("");
      void queryClient.invalidateQueries({ queryKey: ["parent-children"] });
    } catch (err) {
      setError(
        friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1 className="page-title">{t("parentDashboard")}</h1>

      <div className="card">
        <h2>{t("linkChild")}</h2>
        <p className="muted">
          {t("parentInviteHowTo", {
            account: t("account"),
            invite: t("parentInviteTitle"),
          })}
        </p>
        <form onSubmit={link} className="grid-2">
          <div>
            <label htmlFor="icode">{t("inviteCodeLabel")}</label>
            <input
              id="icode"
              className="input"
              value={code}
              placeholder="BGPT-XXXXXXXXXXXXXXXX"
              required
              minLength={8}
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
          <div className="align-end">
            <button className="primary" type="submit" disabled={busy}>
              {busy ? <span className="spinner" aria-hidden /> : t("redeem")}
            </button>
          </div>
        </form>
        {message && (
          <p className="ok" role="status">
            {message}
          </p>
        )}
        {childrenError && (
          <p className="error" role="alert">
            {childrenError}
          </p>
        )}
      </div>

      <div className="card">
        <h2>{t("myChildren")}</h2>
        {children.length === 0 ? (
          <p className="muted">—</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">{t("name")}</th>
                  <th scope="col">{t("className")}</th>
                  <th scope="col">{t("avgScore")}</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {children.map((c) => (
                  <tr key={c.student_id}>
                    <td>{c.student_id}</td>
                    <td>{c.name}</td>
                    <td>{c.class_level}</td>
                    <td>
                      {c.avg_score_pct === null ? "—" : `${c.avg_score_pct}%`}
                    </td>
                    <td>
                      <button
                        className="small secondary"
                        onClick={() => setSelected(c.student_id)}
                      >
                        {t("progressTitle")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected !== null && (
        <ChildSectionState
          title={t("progressTitle")}
          pending={progressQuery.isPending}
          failed={progressQuery.isError}
          onRetry={() => void progressQuery.refetch()}
        />
      )}
      {selected !== null && progress && (
        <div className="card">
          <h2>
            {t("progressTitle")} — {progress.student.name}
          </h2>
          <div className="stat-row">
            <div className="stat">
              <div className="num">{progress.attempts_graded}</div>
              <div className="lbl">{t("gradedQuizzes")}</div>
            </div>
            <div className="stat">
              <div className="num">{progress.avg_score_pct ?? "—"}%</div>
              <div className="lbl">{t("avgScore")}</div>
            </div>
          </div>
          {progress.by_chapter.length > 0 && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">{t("chapter")}</th>
                    <th scope="col">{t("asked")}</th>
                    <th scope="col">{t("correct")}</th>
                    <th scope="col">{t("accuracy")}</th>
                  </tr>
                </thead>
                <tbody>
                  {progress.by_chapter.map((c) => (
                    <tr key={c.chapter}>
                      <td>{c.chapter}</td>
                      <td>{c.asked}</td>
                      <td>{c.correct}</td>
                      <td>
                        {c.accuracy}%
                        {c.accuracy < 60 && (
                          <span className="badge weak"> {t("weak")}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {selected !== null && (
        <ChildSectionState
          title={t("activityTitle")}
          pending={activityQuery.isPending}
          failed={activityQuery.isError}
          onRetry={() => void activityQuery.refetch()}
        />
      )}
      {selected !== null && activity && (
        <div className="card">
          <h2>{t("activityTitle")}</h2>
          <p className="muted m-0">
            {t("streakLabel", { days: activity.streak })} · {t("activityHint")}
          </p>
          <div
            className="heatmap"
            aria-label={t("streakLabel", { days: activity.streak })}
          >
            {activity.days.map((d) => {
              const total = d.questions + d.quizzes;
              const lvl = total === 0 ? 0 : total <= 2 ? 1 : total <= 5 ? 2 : 3;
              const title = [
                d.date,
                t(
                  d.questions === 1 ? "activityQuestion" : "activityQuestions",
                  { n: d.questions },
                ),
                t("activityQuizzes", { n: d.quizzes }),
                t("activityMinutes", { n: d.minutes }),
              ].join(" · ");
              return (
                <span
                  key={d.date}
                  className={`heat-cell lvl-${lvl}`}
                  title={title}
                />
              );
            })}
          </div>
        </div>
      )}
      {selected !== null && (
        <ChildSectionState
          title={`${selectedChild?.name ?? t("studentFallback")} · ${t("progressTitle")}`}
          pending={reportQuery.isPending}
          failed={reportQuery.isError}
          onRetry={() => void reportQuery.refetch()}
        />
      )}
      {selected !== null && report && (
        <div className="card">
          <h2>
            {report.name} · {t("progressTitle")}
          </h2>
          <div
            className="chips mb-2"
            role="group"
            aria-label={t("progressTitle")}
          >
            <button
              className={`chip${period === "weekly" ? " active" : ""}`}
              onClick={() => setPeriod("weekly")}
            >
              {t("periodWeekly")}
            </button>
            <button
              className={`chip${period === "monthly" ? " active" : ""}`}
              onClick={() => setPeriod("monthly")}
            >
              {t("periodMonthly")}
            </button>
          </div>
          <div className="stat-row">
            <div className="stat">
              <div className="num">{report.quizzes_taken}</div>
              <div className="lbl">{t("reportQuizzesGraded")}</div>
            </div>
            <div className="stat">
              <div className="num">
                {report.avg_score_pct == null
                  ? "—"
                  : `${Math.round(report.avg_score_pct)}%`}
              </div>
              <div className="lbl">{t("reportAvg")}</div>
            </div>
            <div className="stat">
              <div className="num">{report.chapters_read}</div>
              <div className="lbl">{t("reportChaptersRead")}</div>
            </div>
            <div className="stat">
              <div className="num">{report.questions_asked}</div>
              <div className="lbl">{t("reportQuestions")}</div>
            </div>
          </div>
          {report.weak_chapters.length > 0 && (
            <p className="mt-2 m-0">
              <span className="muted">{t("reportWeak")}: </span>
              {report.weak_chapters.map((c) => (
                <span key={c} className="badge weak">
                  {" "}
                  {c}
                </span>
              ))}
            </p>
          )}
          {report.strengths.length > 0 && (
            <p className="mt-2 m-0">
              <span className="muted">{t("reportStrengths")}: </span>
              {report.strengths.map((c) => (
                <span key={c} className="badge ok">
                  {" "}
                  {c}
                </span>
              ))}
            </p>
          )}
          <p className="muted mt-2 m-0">
            {t("reportSuggestion")}: {suggestionSentence(report)}
          </p>
        </div>
      )}
    </>
  );
}
