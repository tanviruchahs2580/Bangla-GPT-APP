import { useEffect, useMemo, useState } from "react";
import { get, getTeacherWorkload, post, type TeacherWorkload } from "../../api";
import type {
  ClassRoom,
  Coverage,
  SupportPlanRow,
  WeakMatrix,
} from "../../types";
import { Badge, Button, Card } from "../../components/ui";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";

const errText = (err: unknown): string =>
  friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
  t("errorGeneric");

const STAGE_KEYS: Record<string, string> = {
  concept: "spStageConcept",
  practice: "spStagePractice",
  assessment: "spStageAssessment",
};
const stageLabel = (stage: string): string =>
  STAGE_KEYS[stage] ? t(STAGE_KEYS[stage] as Parameters<typeof t>[0]) : stage;

// S2.7 heatmap bucket -> cell class (colors come from the design tokens only).
const heatClass = (acc: number | null): string =>
  acc === null
    ? "wm-na"
    : acc < 40
      ? "wm-bad"
      : acc < 60
        ? "wm-mid"
        : "wm-good";

// S3.3 coverage cell status -> badge label + tone.
const COV_STATUS_KEYS: Record<string, string> = {
  mastered: "covMastered",
  practiced: "covPracticed",
  taught: "covTaught",
  uncovered: "covUncovered",
};
const COV_STATUS_TONES: Record<string, "default" | "ok" | "warn" | "teal"> = {
  mastered: "ok",
  practiced: "teal",
  uncovered: "warn",
};
const covLabel = (status: string): string =>
  COV_STATUS_KEYS[status]
    ? t(COV_STATUS_KEYS[status] as Parameters<typeof t>[0])
    : status;

export default function AnalyticsPage() {
  const [rooms, setRooms] = useState<ClassRoom[]>([]);
  const [level, setLevel] = useState<number | null>(null);
  const [wm, setWm] = useState<WeakMatrix | null>(null);
  const [cov, setCov] = useState<Coverage | null>(null);
  const [workload, setWorkload] = useState<TeacherWorkload | null>(null);
  const [sps, setSps] = useState<SupportPlanRow[]>([]);
  const [spBusy, setSpBusy] = useState(false);
  const [spMsg, setSpMsg] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    get<ClassRoom[]>("/teacher/classrooms")
      .then((rs) => {
        if (!live) return;
        setRooms(rs);
        setLevel((cur) => cur ?? rs[0]?.class_level ?? null);
      })
      .catch(() => {});
    get<Coverage>("/teacher/curriculum-coverage")
      .then((c) => {
        if (live) setCov(c);
      })
      .catch(() => {
        if (live) setCov(null);
      });
    get<SupportPlanRow[]>("/teacher/support-plans")
      .then((rows) => {
        if (live) setSps(rows ?? []);
      })
      .catch(() => {});
    getTeacherWorkload()
      .then((w) => {
        if (live) setWorkload(w ?? null);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  async function createSupportPlan(studentId: number) {
    if (spBusy) return;
    setSpBusy(true);
    setSpMsg(null);
    try {
      const row = await post<SupportPlanRow>("/teacher/support-plans", {
        student_id: studentId,
      });
      setSps((ls) => [row, ...ls]);
    } catch (err) {
      setSpMsg(errText(err));
    } finally {
      setSpBusy(false);
    }
  }

  useEffect(() => {
    if (level === null) return;
    let live = true;
    setWm(null);
    get<WeakMatrix>(`/teacher/weak-matrix?class_level=${level}`)
      .then((m) => {
        if (live) setWm(m);
      })
      .catch(() => {
        if (live) setWm(null);
      });
    return () => {
      live = false;
    };
  }, [level]);

  // AI Classroom Intelligence: one composite view from existing
  // weak-matrix + coverage data — no new endpoint, no new scoring.
  const ci = useMemo(() => {
    if (!wm) return null;
    const risky = wm.students.filter((s) => s.at_risk).length;
    let weakest: { concept: string; accuracy: number } | null = null;
    for (const s of wm.students) {
      for (const [concept, cell] of Object.entries(s.cells)) {
        if (cell.accuracy === null || cell.asked === 0) continue;
        if (!weakest || cell.accuracy < weakest.accuracy)
          weakest = { concept, accuracy: cell.accuracy };
      }
    }
    const uncovered = cov
      ? Array.from(
          new Set(
            cov.cells
              .filter((c) => c.status === "uncovered")
              .map((c) => c.subject),
          ),
        )
      : [];
    const lines: Array<string> = [];
    if (risky > 0) lines.push(t("anaCiRisk", { n: risky }));
    if (weakest)
      lines.push(
        t("anaCiWeak", {
          concept: weakest.concept,
          pct: Math.round(weakest.accuracy),
        }),
      );
    for (const s of uncovered.slice(0, 2))
      lines.push(t("anaCiCoverage", { subject: s }));
    if (lines.length === 0) lines.push(t("anaCiOk"));
    return { top: lines[0], more: lines.slice(1, 3) };
  }, [wm, cov]);

  const levels = Array.from(new Set(rooms.map((r) => r.class_level)));

  return (
    <main className="shell-main">
      <section className="section-head">
        <h1 className="page-title">{t("tNavAnalytics")}</h1>
      </section>

      {levels.length > 1 && (
        <div
          className="chips chips-gap"
          role="group"
          aria-label={t("selectClass")}
        >
          {levels.map((l) => (
            <button
              key={l}
              className={`chip${level === l ? " active" : ""}`}
              aria-pressed={level === l}
              onClick={() => setLevel(l)}
            >
              {t("classLabel")} {l}
            </button>
          ))}
        </div>
      )}

      <Card title={t("anaCiTitle")}>
        {wm === null ? null : ci === null ? (
          <p className="muted">{t("wmEmpty")}</p>
        ) : (
          <div role="status">
            <p className="ai-insight-line">
              <span aria-hidden>🤖</span> <strong>{t("anaCiTop")}:</strong>{" "}
              {ci.top}
            </p>
            {ci.more.map((m) => (
              <p key={m} className="ai-insight-line muted">
                <span aria-hidden>·</span> {m}
              </p>
            ))}
          </div>
        )}
      </Card>

      <Card title={t("wmTitle")}>
        {wm === null || wm.concepts.length === 0 ? (
          <p className="muted">{t("wmEmpty")}</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{t("wmConcept")}</th>
                  {wm.students.map((s) => (
                    <th key={s.student_id} scope="col">
                      {s.name}
                      {s.at_risk && (
                        <span className="badge badge-warn"> {t("spRisk")}</span>
                      )}
                      {(s.weak_concepts ?? []).length > 0 && (
                        <div className="wm-weak-chips wrap-list mt-1">
                          {(s.weak_concepts ?? []).slice(0, 3).map((c) => (
                            <span key={c} className="badge">
                              {c}
                            </span>
                          ))}
                        </div>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {wm.concepts.map((ch) => (
                  <tr key={ch}>
                    <th scope="row">{ch}</th>
                    {wm.students.map((s) => {
                      const c = s.cells[ch];
                      return (
                        <td
                          key={s.student_id}
                          className={`wm-cell ${heatClass(c ? c.accuracy : null)}`}
                          title={c && c.read ? t("wmRead") : undefined}
                        >
                          {c && c.accuracy !== null
                            ? `${Math.round(c.accuracy)}%`
                            : "·"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                <tr>
                  <th scope="row">
                    {t("wmAvg")} / {t("wmTrend")}
                  </th>
                  {wm.students.map((s) => (
                    <td key={s.student_id} className="wm-cell">
                      {s.avg_score_pct !== null
                        ? `${Math.round(s.avg_score_pct)}%`
                        : "·"}{" "}
                      {s.trend === "down" ? "▼" : s.trend === "up" ? "▲" : "–"}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={t("covTitle")}>
        {cov === null || cov.cells.length === 0 ? (
          <p className="muted">{t("covEmpty")}</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{t("classLabel")}</th>
                  {cov.subjects.map((s) => (
                    <th key={s} scope="col">
                      {s}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from(
                  new Map(cov.cells.map((c) => [c.classroom_id, c])).values(),
                ).map((roomCell) => (
                  <tr key={roomCell.classroom_id}>
                    <th scope="row">{`${roomCell.class_level} · ${roomCell.section}`}</th>
                    {cov.subjects.map((s) => {
                      const c = cov.cells.find(
                        (x) =>
                          x.classroom_id === roomCell.classroom_id &&
                          x.subject === s,
                      );
                      return (
                        <td key={s}>
                          {c ? (
                            <Badge
                              tone={COV_STATUS_TONES[c.status] ?? "default"}
                            >
                              {covLabel(c.status)}
                            </Badge>
                          ) : (
                            "·"
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {wm !== null && wm.students.some((s) => s.at_risk) && (
          <div className="row-flex gap-2 mt-2">
            {wm.students
              .filter((s) => s.at_risk)
              .map((s) => (
                <Button
                  key={s.student_id}
                  variant="soft"
                  size="sm"
                  disabled={spBusy}
                  onClick={() => void createSupportPlan(s.student_id)}
                >
                  {s.name}: {t("spCreate")}
                </Button>
              ))}
          </div>
        )}
        {spMsg && <p className="muted">{spMsg}</p>}
        <h3 className="mt-4">{t("spTitle")}</h3>
        {sps.length === 0 ? (
          <p className="muted">{t("spEmpty")}</p>
        ) : (
          <ul>
            {sps.map((p) => (
              <li key={p.id} className="mb-3">
                <strong>
                  {wm?.students.find((x) => x.student_id === p.student_id)
                    ?.name ?? `#${p.student_id}`}
                </strong>
                {(p.plan.weeks ?? []).map((w) => (
                  <div key={w.week} className="muted">
                    {t("spWeek", { n: w.week })} — {stageLabel(w.stage)}
                    {w.detail ? ` (${w.detail})` : ""}
                  </div>
                ))}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={t("anaCapacity")}>
        <p className="muted muted-sm">{t("anaCapacityHint")}</p>
        {workload ? (
          <div className="stat-row mt-2" title={workload.methodology}>
            <div>
              <div className="num">{workload.total_minutes_saved}</div>
              <div className="lbl">
                {t("workloadMinutes", { n: workload.total_minutes_saved })}
              </div>
            </div>
          </div>
        ) : (
          <p className="muted">{t("noDocumentsYet")}</p>
        )}
      </Card>
    </main>
  );
}
