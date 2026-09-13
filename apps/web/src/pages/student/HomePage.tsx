import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  BookOpen,
  Camera,
  GraduationCap,
  Play,
  Sparkles,
  Zap,
} from "lucide-react";
import { get, type MeResponse } from "../../api";
import type {
  ActivitySummary,
  DashboardSummary,
  StudentProgress,
} from "../../types";
import { useAuth } from "../../AuthContext";
import { Card, ProgressRing, Stat } from "../../components/ui";
import { t, tSubject } from "../../i18n";

function useProgress(me: MeResponse | null) {
  return useQuery({
    queryKey: ["progress", me?.profile_id],
    queryFn: () => get<StudentProgress>(`/students/${me!.profile_id}/progress`),
    enabled: !!me?.profile_id && me.role === "student",
  });
}

function useDashboard(me: MeResponse | null) {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: () => get<DashboardSummary>("/dashboard/summary"),
    enabled: !!me && me.role === "student",
  });
}

function useActivity(me: MeResponse | null) {
  return useQuery({
    queryKey: ["activity", me?.profile_id],
    queryFn: () => get<ActivitySummary>(`/students/${me!.profile_id}/activity`),
    enabled: !!me?.profile_id && me.role === "student",
  });
}

/** WP-DR student home: exactly five primary blocks, nothing more.
 *  1 greeting+prompt  2 continue  3 quick actions  4 recommendation  5 snapshot */
export default function HomePage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const { data: progress, isLoading } = useProgress(me);
  const { data: dashboard } = useDashboard(me);
  const { data: activity } = useActivity(me);

  const avg = progress?.avg_score_pct ?? 0;
  const weak = progress?.weak_chapters ?? [];

  const askTutor = () => {
    const q = prompt.trim();
    navigate("/student/tutor", q ? { state: { ask: q } } : undefined);
  };

  const cont = dashboard?.continue_learning;
  // Fallback to localStorage lastChapter (set by LearnChapterPage)
  let lastLocal: {
    subject: string;
    chapter: string;
    class_level: number;
  } | null = null;
  try {
    const raw = localStorage.getItem("lastChapter");
    if (raw) lastLocal = JSON.parse(raw);
  } catch {}
  const showCont = cont?.chapter
    ? cont
    : lastLocal
      ? {
          subject: lastLocal.subject,
          chapter: lastLocal.chapter,
          class_level: lastLocal.class_level,
          excerpt: null,
        }
      : null;
  const rec = dashboard?.recommendation;

  return (
    <main className="shell-main">
      {/* 1 — greeting + "আজ কী শিখতে চাও?" prompt bar into the AI tutor */}
      <section className="hero">
        <h2>
          {t("welcome")}, {me?.name?.split(/\s+/)[0] ?? t("studentFallback")}!{" "}
          <Sparkles size={20} className="hero-sparkle" aria-hidden />
        </h2>
        <p>{t("whatToDo")}</p>
        <div className="home-prompt row-flex">
          <input
            className="input"
            value={prompt}
            placeholder={t("homePromptPlaceholder")}
            aria-label={t("homePromptPlaceholder")}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && askTutor()}
          />
          <button className="btn btn-primary" onClick={askTutor}>
            <Zap size={18} aria-hidden /> {t("homeAskBtn")}
          </button>
        </div>
      </section>

      {/* 2 — continue learning */}
      {showCont && (
        <Card className="next-step-card">
          <div className="card-title">
            {t("continueLearning")}: {showCont.chapter}
          </div>
          <p className="muted">
            {tSubject(showCont.subject)} · {t("classLabel")}{" "}
            {showCont.class_level}
            {showCont.excerpt ? ` — ${showCont.excerpt.slice(0, 80)}…` : ""}
          </p>
          <button
            className="btn btn-teal"
            onClick={() => {
              const subj = encodeURIComponent(showCont.subject ?? "science");
              const chap = encodeURIComponent(showCont.chapter ?? "");
              const cls = showCont.class_level ?? me?.class_level ?? 6;
              navigate(`/student/learn/${subj}/${chap}?class=${cls}`);
            }}
          >
            <Play size={18} aria-hidden /> {t("continueLearning")}
          </button>
        </Card>
      )}

      {/* 3 — quick actions */}
      <div
        className="quick-grid"
        role="group"
        aria-label={t("quickActionsLabel")}
      >
        <Link to="/student/tutor" className="quick-tile">
          <span className="quick-icon tile-teal" aria-hidden>
            <Camera size={22} />
          </span>
          <span>
            <span className="quick-title quick-title-block">
              {t("quickActionImage")}
            </span>
            <span className="quick-sub">{t("askTutor")}</span>
          </span>
        </Link>
        <Link to="/student/quiz" className="quick-tile">
          <span className="quick-icon tile-warn" aria-hidden>
            <GraduationCap size={22} />
          </span>
          <span>
            <span className="quick-title quick-title-block">
              {t("quickActionPractice")}
            </span>
            <span className="quick-sub">{t("takeQuiz")}</span>
          </span>
        </Link>
        <Link to="/student/learn" className="quick-tile">
          <span className="quick-icon" aria-hidden>
            <BookOpen size={22} />
          </span>
          <span>
            <span className="quick-title quick-title-block">{t("learn")}</span>
            <span className="quick-sub">{t("conceptRead")}</span>
          </span>
        </Link>
        <Link to="/student/tutor" className="quick-tile">
          <span className="quick-icon tile-ai" aria-hidden>
            <Zap size={22} />
          </span>
          <span>
            <span className="quick-title quick-title-block">
              {t("aiTutor")}
            </span>
            <span className="quick-sub">{t("askTutor")}</span>
          </span>
        </Link>
      </div>

      {/* 4 — today's recommendation (weak-chapter rollup) */}
      {rec && rec.chapter && (
        <Card className="next-step-card">
          <div className="card-title">
            {t("todayRecommendation")}: {rec.chapter}
          </div>
          <p className="muted">
            {rec.reason ?? t("weakChapters")} — {tSubject(rec.subject)}
          </p>
          <button
            className="btn btn-soft"
            onClick={() => navigate(`/student/quiz`)}
          >
            <GraduationCap size={18} aria-hidden /> {t("miniQuiz")}
          </button>
        </Card>
      )}

      {/* 5 — compact progress snapshot (streak + accuracy) */}
      <Card className="home-snapshot">
        <div className="card-title">{t("progressSnapshot")}</div>
        {isLoading ? (
          <div className="stack">
            <div className="skeleton" />
            <div className="skeleton skeleton-text" />
          </div>
        ) : progress && progress.attempts_graded > 0 ? (
          <div className="row-flex">
            <ProgressRing
              value={avg}
              size={72}
              label={<strong>{Math.round(avg)}%</strong>}
            />
            <div className="row-main">
              <div className="stat-grid">
                <Stat value={Math.round(avg) + "%"} label={t("avgScore")} />
                <Stat
                  value={activity?.streak ?? 0}
                  label={t("streakLabel", { days: activity?.streak ?? 0 })}
                />
              </div>
              {weak.length > 0 && (
                <div className="weak-chip-row">
                  {weak.slice(0, 3).map((w) => (
                    <span key={w} className="badge badge-warn weak-chip">
                      {w}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => navigate("/student/me")}
            >
              {t("viewFullProgress")}
            </button>
          </div>
        ) : (
          <div className="row-flex">
            <ProgressRing value={0} />
            <div className="row-main">
              <div className="empty-title">{t("notStarted")}</div>
              <div className="muted">{t("takeQuiz")}</div>
            </div>
            <Link to="/student/quiz" className="btn btn-soft">
              {t("takeQuiz")}
            </Link>
          </div>
        )}
      </Card>
    </main>
  );
}
