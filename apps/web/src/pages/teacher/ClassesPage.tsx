import { useCallback, useEffect, useMemo, useState } from "react";
import { get, post } from "../../api";
import type {
  ClassAnalytics,
  ClassRoom,
  ImportResult,
  RosterEntry,
  SupportPlanRow,
  WeakMatrix,
} from "../../types";
import { Badge, Button, Card, ProgressRing, Stat } from "../../components/ui";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";

const errText = (err: unknown): string =>
  friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
  t("errorGeneric");

type Health = "strong" | "support" | "risk";

// Class health from existing at-risk buckets only — no new scoring model.
function healthOf(atRisk: number, avg: number | null): Health {
  if (atRisk > 0) return "risk";
  if (avg !== null && avg < 60) return "support";
  return "strong";
}

const HEALTH_DOT: Record<Health, string> = {
  strong: "🟢",
  support: "🟡",
  risk: "🔴",
};
const HEALTH_LABEL: Record<Health, string> = {
  strong: t("sdStrong"),
  support: t("sdSupport"),
  risk: t("clsRisk"),
};

export default function ClassesPage() {
  const [rooms, setRooms] = useState<ClassRoom[]>([]);
  const [roomId, setRoomId] = useState<number | null>(null);
  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [analytics, setAnalytics] = useState<ClassAnalytics | null>(null);
  const [wm, setWm] = useState<WeakMatrix | null>(null);
  const [sps, setSps] = useState<SupportPlanRow[]>([]);
  const [spBusy, setSpBusy] = useState(false);
  const [spMsg, setSpMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "strong" | "support" | "risk">(
    "all",
  );

  const [newLevel, setNewLevel] = useState(6);
  const [newSection, setNewSection] = useState("GEN");
  const [createBusy, setCreateBusy] = useState(false);

  const [csvText, setCsvText] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);

  const selected = rooms.find((r) => r.id === roomId) ?? null;

  const loadRooms = useCallback(() => {
    get<ClassRoom[]>("/teacher/classrooms")
      .then((rs) => {
        setRooms(rs);
        setRoomId((cur) =>
          cur !== null && rs.some((r) => r.id === cur)
            ? cur
            : (rs[0]?.id ?? null),
        );
      })
      .catch((err: unknown) => setError(errText(err)));
  }, []);

  useEffect(() => {
    loadRooms();
  }, [loadRooms]);

  const load = useCallback(() => {
    if (roomId === null) {
      setRoster([]);
      setAnalytics(null);
      setWm(null);
      return;
    }
    setError(null);
    Promise.all([
      get<RosterEntry[]>(`/teacher/classrooms/${roomId}/roster`),
      selected
        ? get<ClassAnalytics>(
            `/teacher/classes/${selected.class_level}/analytics`,
          )
        : Promise.resolve(null),
      selected
        ? get<WeakMatrix>(
            `/teacher/weak-matrix?class_level=${selected.class_level}`,
          ).catch(() => null)
        : Promise.resolve(null),
      get<SupportPlanRow[]>("/teacher/support-plans").catch(() => []),
    ])
      .then(([r, a, m, plans]) => {
        setRoster(r);
        setAnalytics(a);
        setWm(m ?? null);
        setSps(plans ?? []);
      })
      .catch((err: unknown) => setError(errText(err)));
  }, [roomId, selected]);

  useEffect(() => {
    load();
  }, [load]);

  async function createRoom(e: React.FormEvent) {
    e.preventDefault();
    if (createBusy) return;
    setCreateBusy(true);
    setError(null);
    try {
      const room = await post<ClassRoom>("/teacher/classrooms", {
        class_level: newLevel,
        section: newSection || "GEN",
      });
      setRooms((rs) =>
        [...rs, room].sort(
          (a, b) =>
            a.class_level - b.class_level || a.section.localeCompare(b.section),
        ),
      );
      setRoomId(room.id);
    } catch (err) {
      setError(errText(err));
    } finally {
      setCreateBusy(false);
    }
  }

  async function runImport(e: React.FormEvent) {
    e.preventDefault();
    if (roomId === null || importBusy || !csvText.trim()) return;
    setImportBusy(true);
    setImportResult(null);
    try {
      const res = await post<ImportResult>(
        `/teacher/classrooms/${roomId}/import`,
        { csv_text: csvText },
      );
      setImportResult(res);
      setCsvText("");
      load();
      loadRooms();
    } catch (err) {
      setError(errText(err));
    } finally {
      setImportBusy(false);
    }
  }

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

  const wmStudent = (id: number) =>
    wm?.students.find((s) => s.student_id === id) ?? null;

  // Roster filters, fed by existing roster + weak-matrix at-risk flags.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return roster.filter((s) => {
      if (
        q &&
        !s.name.toLowerCase().includes(q) &&
        !(s.email ?? "").toLowerCase().includes(q)
      )
        return false;
      if (filter === "all") return true;
      const w = wmStudent(s.student_id);
      const h = healthOf(w?.at_risk ? 1 : 0, s.avg_score_pct);
      return filter === "strong"
        ? h === "strong"
        : filter === "support"
          ? h === "support"
          : h === "risk";
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roster, search, filter, wm]);

  const detail =
    detailId !== null
      ? (roster.find((s) => s.student_id === detailId) ?? null)
      : null;
  const detailWm = detail ? wmStudent(detail.student_id) : null;
  const detailPlans =
    detail !== null
      ? sps.filter((p) => p.student_id === detail.student_id)
      : [];

  const classHealth = selected
    ? healthOf(
        (wm?.students ?? []).filter((s) => s.at_risk).length,
        analytics
          ? (() => {
              const rows = analytics.chapters.filter((c) => c.asked > 0);
              if (rows.length === 0) return null;
              return rows.reduce((sum, c) => sum + c.accuracy, 0) / rows.length;
            })()
          : null,
      )
    : null;

  const insight = useMemo(() => {
    if (!wm) return null;
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
        vars: {
          concept: weakest.concept,
          pct: Math.round(weakest.accuracy),
        },
      };
    return { key: "thInsightOk" as const, vars: {} };
  }, [wm]);

  return (
    <main className="shell-main">
      <section className="section-head">
        <h1 className="page-title">{t("tNavClasses")}</h1>
        <Button variant="soft" size="sm" onClick={loadRooms}>
          {t("refreshBtn")}
        </Button>
      </section>

      <div className="card">
        <div
          className="row-flex gap-2"
          role="group"
          aria-label={t("classrooms")}
        >
          {rooms.map((r) => (
            <button
              key={r.id}
              className={`chip${r.id === roomId ? " active" : ""}`}
              aria-pressed={r.id === roomId}
              onClick={() => {
                setRoomId(r.id);
                setDetailId(null);
              }}
            >
              {t("className").replace(/\s*\(.*\)/, "")} {r.class_level} ·{" "}
              {r.section} ({r.student_count})
            </button>
          ))}
          {rooms.length === 0 && <p className="muted">{t("noStudents")}</p>}
        </div>
        <form onSubmit={createRoom} className="row-flex gap-2 mt-2">
          <label htmlFor="ncls">{t("newClassroom")}</label>
          <select
            id="ncls"
            className="select"
            value={newLevel}
            onChange={(e) => setNewLevel(Number(e.target.value))}
          >
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <input
            id="nsec"
            value={newSection}
            maxLength={8}
            className="input w-90"
            aria-label={t("section")}
            onChange={(e) => setNewSection(e.target.value)}
          />
          <button
            className="small secondary"
            type="submit"
            disabled={createBusy}
          >
            {t("newClassroom")}
          </button>
        </form>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>

      {selected && (
        <Card title={t("clsOverview")}>
          <div className="row-flex chips-gap">
            <Badge tone="teal">
              {t("classLabel")} {selected.class_level} · {selected.section}
            </Badge>
            {classHealth && (
              <Badge
                tone={
                  classHealth === "risk"
                    ? "warn"
                    : classHealth === "strong"
                      ? "ok"
                      : "teal"
                }
              >
                {HEALTH_DOT[classHealth]} {HEALTH_LABEL[classHealth]}
              </Badge>
            )}
          </div>
          {analytics && (
            <div className="stat-row section-gap-top">
              <Stat value={analytics.students} label={t("students")} />
              <Stat value={analytics.chapters.length} label={t("chapter")} />
              <Stat
                value={analytics.weak_chapters.length}
                label={t("weakChapters")}
              />
            </div>
          )}
          {insight && (
            <p className="ai-insight-line section-gap-top" role="status">
              <span aria-hidden>🤖</span>{" "}
              {t(insight.key, insight.vars as Record<string, string | number>)}
            </p>
          )}
        </Card>
      )}

      {detail ? (
        <Card title={t("clsStudentTitle")}>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setDetailId(null)}
            aria-label={t("clsBackToList")}
          >
            ← {t("clsBackToList")}
          </Button>
          <div className="row-flex section-gap-top gap-4">
            <ProgressRing
              value={detail.avg_score_pct ?? 0}
              size={84}
              label={
                <strong>
                  {detail.avg_score_pct === null
                    ? "—"
                    : `${Math.round(detail.avg_score_pct)}%`}
                </strong>
              }
            />
            <div className="row-main">
              <div className="row-title">{detail.name}</div>
              <div className="row-sub">
                {detail.email ?? `#${detail.student_id}`}
              </div>
              <div className="row-sub">
                {t("clsMastery")}:{" "}
                {detail.avg_score_pct === null
                  ? "—"
                  : `${Math.round(detail.avg_score_pct)}%`}{" "}
                · {t("gradedQuizzes")}: {detail.attempts_graded}
                {detailWm && (
                  <>
                    {" "}
                    · {t("wmTrend")}:{" "}
                    {detailWm.trend === "down"
                      ? "▼"
                      : detailWm.trend === "up"
                        ? "▲"
                        : "–"}
                    {detailWm.at_risk && (
                      <Badge tone="warn"> {t("spRisk")}</Badge>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
          <div className="section-gap-top">
            <div className="card-title">{t("clsWeakConcepts")}</div>
            {(!detailWm?.weak_concepts ||
              detailWm.weak_concepts.length === 0) && (
              <p className="muted muted-sm">{t("clsNoWeakConcepts")}</p>
            )}
            <div className="chips">
              {(detailWm?.weak_concepts ?? []).slice(0, 6).map((c) => (
                <span key={c} className="badge badge-warn">
                  {c}
                </span>
              ))}
            </div>
          </div>
          <div className="section-gap-top">
            <div className="card-title">{t("clsRecommend")}</div>
            <p className="muted muted-sm">
              {detailWm?.at_risk
                ? t("thInsightRisk", { n: 1 })
                : detailWm?.weak_concepts?.length
                  ? t("nextSuggestionPractice")
                  : t("thInsightOk")}
            </p>
          </div>
          <div className="section-gap-top">
            <Button
              variant="primary"
              size="sm"
              loading={spBusy}
              onClick={() => void createSupportPlan(detail.student_id)}
            >
              {t("spCreate")}
            </Button>
            {spMsg && <p className="muted">{spMsg}</p>}
            {detailPlans.length > 0 && (
              <ul className="section-gap-top">
                {detailPlans.map((p) => (
                  <li key={p.id}>
                    <strong>{t("spTitle")}</strong>
                    {(p.plan.weeks ?? []).map((w) => (
                      <div key={w.week} className="muted">
                        {t("spWeek", { n: w.week })} —{" "}
                        {t(
                          (w.stage === "concept"
                            ? "spStageConcept"
                            : w.stage === "practice"
                              ? "spStagePractice"
                              : "spStageAssessment") as Parameters<typeof t>[0],
                        )}
                        {w.detail ? ` (${w.detail})` : ""}
                      </div>
                    ))}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      ) : (
        <Card title={t("classStudents")}>
          <div className="row-flex chips-gap">
            <input
              className="input maxw-220"
              value={search}
              placeholder={t("clsSearchStudent")}
              aria-label={t("clsSearchStudent")}
              onChange={(e) => setSearch(e.target.value)}
            />
            {(
              [
                ["all", "genAll"],
                ["strong", "sdStrong"],
                ["support", "sdSupport"],
                ["risk", "clsRisk"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                className={`chip${filter === value ? " active" : ""}`}
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
              >
                {t(label)}
              </button>
            ))}
          </div>
          {filtered.length === 0 ? (
            <p className="muted">{t("noStudents")}</p>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">{t("name")}</th>
                    <th scope="col">
                      {t("className").replace(/\s*\(.*\)/, "")}
                    </th>
                    <th scope="col">{t("quizTitle")}</th>
                    <th scope="col">{t("avgScore")}</th>
                    <th scope="col"></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((s) => {
                    const w = wmStudent(s.student_id);
                    const h = healthOf(w?.at_risk ? 1 : 0, s.avg_score_pct);
                    return (
                      <tr key={s.student_id}>
                        <td>{s.student_id}</td>
                        <td>
                          {s.name}
                          {s.email && (
                            <div className="muted text-sm">{s.email}</div>
                          )}
                          {s.invite_pending && (
                            <span className="badge"> {t("invitePending")}</span>
                          )}
                        </td>
                        <td>{s.class_level}</td>
                        <td>{s.attempts_graded}</td>
                        <td>
                          {s.avg_score_pct === null
                            ? "—"
                            : `${s.avg_score_pct}%`}
                          <span aria-hidden> {HEALTH_DOT[h]}</span>
                          <span className="visually-hidden">
                            {HEALTH_LABEL[h]}
                          </span>
                        </td>
                        <td>
                          <Button
                            variant="soft"
                            size="sm"
                            onClick={() => setDetailId(s.student_id)}
                          >
                            {t("cOpen")}
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {selected && (
        <Card title={t("csvImport")}>
          <p className="muted">{t("csvHint")}</p>
          <form onSubmit={runImport}>
            <textarea
              rows={5}
              className="textarea mono-block"
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
              placeholder={"name,email"}
            />
            <Button
              variant="primary"
              type="submit"
              loading={importBusy}
              disabled={!csvText.trim()}
            >
              {t("importBtn")}
            </Button>
          </form>
          {importResult && (
            <div role="status">
              <p>
                <span>{t("importCreated", { n: importResult.created })}</span>
                {" · "}
                <span>{t("importFailed", { n: importResult.failed })}</span>
              </p>
              {importResult.rows.some((r) => r.invite_code) && (
                <div className="table-wrap">
                  <table className="data">
                    <tbody>
                      {importResult.rows
                        .filter((r) => r.invite_code)
                        .map((r) => (
                          <tr key={r.email}>
                            <td>{r.name}</td>
                            <td>{r.email}</td>
                            <td>
                              {t("inviteCode")}: <code>{r.invite_code}</code>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </Card>
      )}
    </main>
  );
}
