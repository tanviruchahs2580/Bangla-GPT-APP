import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  BookOpen,
  GraduationCap,
  Zap,
  ArrowRight,
  Sparkles,
  Play,
} from "lucide-react";
import { get, type MeResponse } from "../../api";
import type { DashboardSummary, StudentProgress } from "../../types";
import { useAuth } from "../../AuthContext";
import { Button, Card, ProgressRing, Stat } from "../../components/ui";
import { t } from "../../i18n";

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

export default function HomePage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const { data: progress, isLoading } = useProgress(me);
  const { data: dashboard } = useDashboard(me);

  const avg = progress?.avg_score_pct ?? 0;
  const graded = progress?.attempts_graded ?? 0;
  const weak = progress?.weak_chapters ?? [];

  return (
    <main className="shell-main">
      <section className="hero">
        <h2>
          {t("welcome")}, {me?.name?.split(/\s+/)[0] ?? "শিক্ষার্থী"}!{" "}
          <Sparkles size={20} className="hero-sparkle" aria-hidden />
        </h2>
        <p>{t("whatToDo")}</p>
        <div className="hero-actions">
          <Link to="/student/learn" className="btn btn-teal">
            <BookOpen size={18} aria-hidden /> {t("startLearning")}
          </Link>
          <Link to="/student/tutor" className="btn hero-btn-glass">
            <Zap size={18} aria-hidden /> {t("askTutor")}
          </Link>
        </div>
      </section>

      <section className="section-head">
        <h2>{t("browseCurriculum")}</h2>
        <Link to="/student/learn" className="row-flex">
          {t("chapters")} <ArrowRight size={16} aria-hidden />
        </Link>
      </section>

      <div className="quick-grid">
        <Link to="/student/learn" className="quick-tile">
          <span className="quick-icon">
            <BookOpen size={22} aria-hidden />
          </span>
          <span>
            <span className="quick-title quick-title-block">{t("learn")}</span>
            <span className="quick-sub">{t("conceptRead")}</span>
          </span>
        </Link>
        <Link to="/student/tutor" className="quick-tile">
          <span className="quick-icon tile-teal">
            <Zap size={22} aria-hidden />
          </span>
          <span>
            <span className="quick-title quick-title-block">
              {t("aiTutor")}
            </span>
            <span className="quick-sub">{t("askTutor")}</span>
          </span>
        </Link>
        <Link to="/student/quiz" className="quick-tile">
          <span className="quick-icon tile-warn">
            <GraduationCap size={22} aria-hidden />
          </span>
          <span>
            <span className="quick-title quick-title-block">{t("quiz")}</span>
            <span className="quick-sub">{t("takeQuiz")}</span>
          </span>
        </Link>
      </div>

      <section className="section-head">
        <h2>{t("myProgress")}</h2>
      </section>

      <Card>
        {isLoading ? (
          <div className="stack">
            <div className="skeleton" />
            <div className="skeleton skeleton-text" />
          </div>
        ) : graded === 0 ? (
          <div className="row-flex">
            <ProgressRing value={0} />
            <div className="row-main">
              <div className="empty-title">{t("notStarted")}</div>
              <div className="muted">{t("takeQuiz")}</div>
            </div>
            <Button variant="soft" onClick={() => navigate("/student/quiz")}>
              {t("takeQuiz")}
            </Button>
          </div>
        ) : (
          <>
            <div className="row-flex progress-hero-row">
              <ProgressRing
                value={avg}
                size={96}
                label={<strong>{Math.round(avg)}%</strong>}
              />
              <div>
                <div className="stat-value">{Math.round(avg)}%</div>
                <div className="stat-label">{t("avgScore")}</div>
              </div>
            </div>
            <div className="stat-grid section-gap-top">
              <Stat value={graded} label={t("gradedQuizzes")} />
              <Stat value={weak.length} label={t("weakChapters")} />
            </div>
            {weak.length > 0 && (
              <div className="weak-chip-row">
                <span className="muted muted-sm">{t("weakChapters")}:</span>
                {weak.slice(0, 4).map((w) => (
                  <button
                    key={w}
                    type="button"
                    className="badge badge-warn weak-chip"
                    onClick={() => navigate("/student/learn")}
                    aria-label={w}
                  >
                    {w}
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </Card>

      {(() => {
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
          <>
            {showCont && (
              <Card className="next-step-card">
                <div className="card-title">
                  চালিয়ে যান: {showCont.chapter}
                </div>
                <p className="muted">
                  {showCont.subject} · শ্রেণি {showCont.class_level}
                  {showCont.excerpt
                    ? ` — ${showCont.excerpt.slice(0, 80)}…`
                    : ""}
                </p>
                <Button
                  variant="teal"
                  onClick={() => {
                    const subj = encodeURIComponent(
                      showCont.subject ?? "science",
                    );
                    const chap = encodeURIComponent(showCont.chapter ?? "");
                    const cls = showCont.class_level ?? me?.class_level ?? 6;
                    navigate(`/student/learn/${subj}/${chap}?class=${cls}`);
                  }}
                >
                  <Play size={18} aria-hidden /> চালিয়ে যান
                </Button>
              </Card>
            )}
            {rec && rec.chapter && (
              <Card className="next-step-card">
                <div className="card-title">প্রস্তাবিত: {rec.chapter}</div>
                <p className="muted">
                  {rec.reason ?? "দুর্বল অধ্যায়"} — {rec.subject}
                </p>
                <Button
                  variant="soft"
                  onClick={() => navigate(`/student/quiz`)}
                >
                  <GraduationCap size={18} aria-hidden /> মিনি কুইজ (3 প্রশ্ন)
                </Button>
              </Card>
            )}
            <Card>
              <div className="card-title">{t("lessonsNote")}</div>
              <Button
                variant="primary"
                onClick={() => navigate("/student/learn")}
              >
                <BookOpen size={18} aria-hidden /> {t("browseCurriculum")}
              </Button>
            </Card>
          </>
        );
      })()}
    </main>
  );
}
