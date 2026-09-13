import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookOpen,
  ClipboardList,
  FileText,
  NotebookPen,
  Timer,
} from "lucide-react";
import { get, getTeacherWorkload, type TeacherWorkload } from "../../api";
import type { ClassRoom, QPaper, WeakMatrix } from "../../types";
import { Card, Stat } from "../../components/ui";
import { useAuth } from "../../AuthContext";
import { t } from "../../i18n";

// ✨ Quick Create shortcuts -> deep links into Create (?kind=…).
const QUICK = [
  { kind: "question_paper", label: "qpTitle", icon: FileText },
  { kind: "short_test", label: "stTitle", icon: Timer },
  { kind: "worksheet", label: "genWorksheet", icon: BookOpen },
  { kind: "lesson_plan", label: "lpTitle", icon: NotebookPen },
  { kind: "quiz", label: "cQuizEntry", icon: ClipboardList },
] as const;

export default function TeacherHomePage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [rooms, setRooms] = useState<ClassRoom[]>([]);
  const [drafts, setDrafts] = useState<number | null>(null);
  const [wm, setWm] = useState<WeakMatrix | null>(null);
  const [workload, setWorkload] = useState<TeacherWorkload | null>(null);

  useEffect(() => {
    let live = true;
    get<ClassRoom[]>("/teacher/classrooms")
      .then((rs) => {
        if (!live) return;
        setRooms(rs ?? []);
        // AI insight rides the first class's existing weak-matrix data.
        const level = rs?.[0]?.class_level;
        if (level != null) {
          get<WeakMatrix>(`/teacher/weak-matrix?class_level=${level}`)
            .then((m) => {
              if (live) setWm(m);
            })
            .catch(() => {
              if (live) setWm(null);
            });
        }
      })
      .catch(() => {});
    get<QPaper[]>("/teacher/qpapers")
      .then((rows) => {
        if (live)
          setDrafts((rows ?? []).filter((q) => q.status !== "final").length);
      })
      .catch(() => {
        if (live) setDrafts(null);
      });
    getTeacherWorkload()
      .then((w) => {
        if (live) setWorkload(w ?? null);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const students = useMemo(
    () => rooms.reduce((sum, r) => sum + r.student_count, 0),
    [rooms],
  );

  const insight = useMemo(() => {
    if (!wm || wm.students.length === 0) return null;
    const risky = wm.students.filter((s) => s.at_risk).length;
    if (risky > 0) return { key: "thInsightRisk" as const, vars: { n: risky } };
    let weakest: { concept: string; accuracy: number } | null = null;
    for (const s of wm.students) {
      for (const [concept, cell] of Object.entries(s.cells)) {
        if (cell.accuracy === null || cell.asked === 0) continue;
        if (!weakest || cell.accuracy < weakest.accuracy)
          weakest = { concept, accuracy: cell.accuracy };
      }
    }
    if (weakest)
      return {
        key: "thInsightWeak" as const,
        vars: { concept: weakest.concept, pct: Math.round(weakest.accuracy) },
      };
    return { key: "thInsightOk" as const, vars: {} };
  }, [wm]);

  return (
    <main className="shell-main">
      <section className="hero teacher-hero">
        <h2>{t("thGreeting", { name: me?.name?.split(/\s+/)[0] ?? "" })}</h2>
        <p>{t("teacherDashboard")}</p>
      </section>

      <div className="stat-row">
        <Stat value={students} label={t("students")} />
        <Stat value={rooms.length} label={t("thClassesStat")} />
        <Stat value={drafts ?? "—"} label={t("thDraftsStat")} />
      </div>

      <Card title={t("thQuickCreate")}>
        <div className="create-grid create-grid-compact" role="list">
          {QUICK.map(({ kind, label, icon: Icon }) => (
            <button
              key={kind}
              role="listitem"
              className="create-tile"
              onClick={() => navigate(`/teacher/create?kind=${kind}`)}
            >
              <span className="quick-icon" aria-hidden>
                <Icon size={20} />
              </span>
              <span className="create-tile-body">
                <span className="quick-title quick-title-block">
                  {t(label as Parameters<typeof t>[0])}
                </span>
              </span>
            </button>
          ))}
        </div>
      </Card>

      <Card title={t("thAiInsight")}>
        {rooms.length === 0 ? (
          <p className="muted">{t("thInsightNoData")}</p>
        ) : insight === null ? (
          <p className="muted">{t("wmEmpty")}</p>
        ) : (
          <p className="ai-insight-line" role="status">
            <span aria-hidden>🤖</span>{" "}
            {t(insight.key, insight.vars as Record<string, string | number>)}
          </p>
        )}
      </Card>

      {workload && (
        <div
          className="stat-row"
          title={workload.methodology}
          aria-label={t("thWorkloadTitle")}
        >
          <div>
            <div className="num">{workload.total_minutes_saved}</div>
            <div className="lbl">{t("thWorkloadTitle")}</div>
          </div>
          <p className="muted muted-sm">
            {t("workloadMinutes", { n: workload.total_minutes_saved })}
          </p>
        </div>
      )}
    </main>
  );
}
