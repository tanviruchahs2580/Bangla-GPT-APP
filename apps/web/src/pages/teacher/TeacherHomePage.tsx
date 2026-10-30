import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  ClipboardList,
  FileText,
  NotebookPen,
  Sparkles,
  Timer,
} from "lucide-react";
import { get, getTeacherWorkload } from "../../api";
import type { ClassRoom, QPaper, WeakMatrix } from "../../types";
import { Card, Stat } from "../../components/ui";
import { useAuth } from "../../AuthContext";
import { t } from "../../i18n";

// Quick Create shortcuts -> deep links into Create (?kind=…).
const QUICK = [
  { kind: "question_paper", label: "qpTitle", icon: FileText },
  { kind: "short_test", label: "stTitle", icon: Timer },
  { kind: "worksheet", label: "genWorksheet", icon: BookOpen },
  { kind: "lesson_plan", label: "lpTitle", icon: NotebookPen },
  { kind: "quiz", label: "cQuizEntry", icon: ClipboardList },
] as const;

/**
 * Teacher home on the shared query cache (audit H-04: this module ran its
 * own useState/useEffect fetches — no dedupe against ClassesPage's identical
 * classrooms read, no retry, and nothing invalidated the counts after a
 * generation). Keys mirror the other teacher pages so one cache serves both.
 */
export default function TeacherHomePage() {
  const { me } = useAuth();
  const navigate = useNavigate();

  const roomsQuery = useQuery({
    queryKey: ["teacher", "classrooms"],
    queryFn: () => get<ClassRoom[]>("/teacher/classrooms"),
  });
  const draftsQuery = useQuery({
    queryKey: ["teacher", "qpapers"],
    queryFn: () => get<QPaper[]>("/teacher/qpapers"),
    select: (rows) => rows.filter((q) => q.status !== "final").length,
  });
  const workloadQuery = useQuery({
    queryKey: ["teacher", "workload"],
    queryFn: () => getTeacherWorkload(),
  });

  // stable identity while loading: the auto-select effect and the
  // students memo key on this array
  const rooms = useMemo(() => roomsQuery.data ?? [], [roomsQuery.data]);
  // AI insight rides the first class's existing weak-matrix data, scoped to
  // that classroom's roster (not the whole grade).
  const first = rooms[0];
  const wmQuery = useQuery({
    queryKey: ["teacher", "weak-matrix", first?.class_level, first?.id],
    queryFn: () =>
      get<WeakMatrix>(
        `/teacher/weak-matrix?class_level=${first.class_level}&room_id=${first.id}`,
      ),
    enabled: first != null,
    retry: false, // the insight is best-effort: an empty matrix is normal
  });

  const loadError = roomsQuery.isError || workloadQuery.isError;
  const retry = () => {
    void roomsQuery.refetch();
    void workloadQuery.refetch();
  };

  const students = useMemo(
    () => rooms.reduce((sum, r) => sum + r.student_count, 0),
    [rooms],
  );
  const drafts = draftsQuery.data ?? null;
  const wm = wmQuery.data ?? null;
  const workload = workloadQuery.data ?? null;

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
    <main id="main-content" tabIndex={-1} className="shell-main">
      {loadError && (
        <div className="muted" role="status">
          {t("thLoadError")}{" "}
          <button className="btn btn-sm btn-ghost" onClick={retry}>
            {t("retry")}
          </button>
        </div>
      )}
      <section className="hero teacher-hero">
        <h1>{t("thGreeting", { name: me?.name ?? "" })}</h1>
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
            <div role="listitem" key={kind}>
              <button
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
            </div>
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
            <Sparkles size={16} aria-hidden />
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
