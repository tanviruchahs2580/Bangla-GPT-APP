import { useCallback, useEffect, useState } from "react";
import { get, getParentReport, post } from "../api";
import type { ParentReport } from "../api";
import { friendlyError } from "../errors";
import { t } from "../i18n";
import { track } from "../lib/analytics";
import type { ActivitySummary, StudentBrief, StudentProgress } from "../types";

// Server sends a suggestion CODE + params; the client renders the sentence (i18n).
function suggestionSentence(report: ParentReport): string {
  const key = report.suggestion_code as Parameters<typeof t>[0];
  const vars: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(report.suggestion_params ?? {})) {
    vars[k] = Array.isArray(v) ? v.join(", ") : String(v ?? "");
  }
  try {
    const text = t(key, vars);
    if (text && text !== report.suggestion_code) return text;
  } catch {
    // unknown code falls through to the raw code below
  }
  return report.suggestion_code;
}

export default function ParentDashboard() {
  const [children, setChildren] = useState<StudentBrief[]>([]);
  const [code, setCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [progress, setProgress] = useState<StudentProgress | null>(null);
  const [activity, setActivity] = useState<ActivitySummary | null>(null);
  const [report, setReport] = useState<ParentReport | null>(null);
  const [period, setPeriod] = useState<"weekly" | "monthly">("weekly");

  const loadChildren = useCallback(() => {
    get<StudentBrief[]>("/parents/me/children")
      .then(setChildren)
      .catch((err: unknown) =>
        setError(
          friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
            t("errorGeneric"),
        ),
      );
  }, []);

  useEffect(() => {
    loadChildren();
  }, [loadChildren]);

  useEffect(() => {
    if (selected === null) {
      setProgress(null);
      setReport(null);
      setActivity(null);
      return;
    }
    get<StudentProgress>(`/parents/me/children/${selected}/progress`)
      .then(setProgress)
      .catch((err: unknown) =>
        setError(
          friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
            t("errorGeneric"),
        ),
      );
    get<ActivitySummary>(`/parents/me/children/${selected}/activity`)
      .then(setActivity)
      .catch(() => setActivity(null));
    getParentReport(selected, period)
      .then((r) => {
        setReport(r);
        track("report_viewed", { role: "parent", period });
      })
      .catch(() => setReport(null));
  }, [selected, period]);

  async function link(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      // C17: single-use invite code issued by the child — no bare IDs.
      await post("/parents/link/invite", { code: code.trim().toUpperCase() });
      setMessage(t("myChildren") + " ✓");
      setCode("");
      loadChildren();
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
          সন্তানের অ্যাকাউন্টে লগইন করে “{t("account")}” → “
          {t("parentInviteTitle")}” কোড তৈরি করুন।
        </p>
        <form onSubmit={link} className="grid-2">
          <div>
            <label htmlFor="icode">{t("inviteCodeLabel")}</label>
            <input
              id="icode"
              className="input"
              value={code}
              placeholder="BGPT-XXXXXXXX"
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
        {error && (
          <p className="error" role="alert">
            {error}
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
                t("activityQuestions", { n: d.questions }),
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
