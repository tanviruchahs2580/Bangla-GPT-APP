import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
  strong: "dot-strong",
  support: "dot-support",
  risk: "dot-risk",
};
// Keys, not copy. A module-level table of t(...) results is evaluated once, when
// the module is first imported, so it kept whichever language was active then:
// a teacher who switched to English still saw these badges and the legend in
// Bengali until a hard reload. t() is called at render time instead.
const HEALTH_LABEL_KEY: Record<Health, Parameters<typeof t>[0]> = {
  strong: "sdStrong",
  support: "sdSupport",
  risk: "clsRisk",
};

export default function ClassesPage() {
  const queryClient = useQueryClient();
  const [roomId, setRoomId] = useState<number | null>(null);
  const [spBusy, setSpBusy] = useState(false);
  const [spMsg, setSpMsg] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
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

  // Shared cache (audit H-04: this page ran five ad-hoc fetches per mount;
  // TeacherHomePage reads the same classrooms list through the same key, so
  // navigation between them no longer refetches or disagrees).
  const roomsQuery = useQuery({
    queryKey: ["teacher", "classrooms"],
    queryFn: () => get<ClassRoom[]>("/teacher/classrooms"),
    select: (rs) =>
      [...rs].sort(
        (a, b) =>
          a.class_level - b.class_level || a.section.localeCompare(b.section),
      ),
  });
  // stable identity while loading: the auto-select effect and the
  // students memo key on this array
  const rooms = useMemo(() => roomsQuery.data ?? [], [roomsQuery.data]);

  // Auto-select the first room (or keep the selection valid after a refetch).
  useEffect(() => {
    if (rooms.length === 0) {
      setRoomId(null);
      return;
    }
    setRoomId((cur) =>
      cur !== null && rooms.some((r) => r.id === cur) ? cur : rooms[0].id,
    );
  }, [rooms]);

  const selected = rooms.find((r) => r.id === roomId) ?? null;

  const rosterQuery = useQuery({
    queryKey: ["teacher", "roster", roomId],
    queryFn: () => get<RosterEntry[]>(`/teacher/classrooms/${roomId}/roster`),
    enabled: roomId !== null,
  });
  const analyticsQuery = useQuery({
    queryKey: ["teacher", "classAnalytics", selected?.class_level],
    queryFn: () =>
      get<ClassAnalytics>(`/teacher/classes/${selected?.class_level}/analytics`),
    enabled: selected !== null,
  });
  const wmQuery = useQuery({
    // Roster-scoped matrix: an empty classroom must show its own (empty)
    // stats, not the grade-wide platform numbers.
    queryKey: ["teacher", "weak-matrix", selected?.class_level, selected?.id],
    queryFn: () =>
      get<WeakMatrix>(
        `/teacher/weak-matrix?class_level=${selected?.class_level}&room_id=${selected?.id}`,
      ),
    enabled: selected !== null,
    retry: false, // an unscorable room shows its empty state, not an error
  });
  const plansQuery = useQuery({
    queryKey: ["teacher", "support-plans"],
    queryFn: () => get<SupportPlanRow[]>("/teacher/support-plans"),
  });

  const roster = rosterQuery.data ?? [];
  const analytics = analyticsQuery.data ?? null;
  const wm = wmQuery.data ?? null;
  const sps = plansQuery.data ?? [];

  // The banner reports what a teacher can act on: a failed rooms load (page
  // unusable) or a failed mutation. Per-panel loads (roster/analytics/wm)
  // render their own empty/partial states — a dead analytics panel must not
  // blank the roster underneath it.
  const queryError =
    roomsQuery.error ??
    (rosterQuery.isError && roomId !== null ? rosterQuery.error : null);
  const error = mutationError ?? (queryError ? errText(queryError) : null);
  const refresh = () => {
    setMutationError(null);
    void roomsQuery.refetch();
    void rosterQuery.refetch();
  };

  async function createRoom(e: React.FormEvent) {
    e.preventDefault();
    if (createBusy) return;
    setCreateBusy(true);
    setMutationError(null);
    try {
      const room = await post<ClassRoom>("/teacher/classrooms", {
        class_level: newLevel,
        section: newSection || "GEN",
      });
      setRoomId(room.id);
      void queryClient.invalidateQueries({ queryKey: ["teacher", "classrooms"] });
    } catch (err) {
      setMutationError(errText(err));
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
        // 200 rows = 200 Argon2id hashes server-side (measured past the
        // 20s default guard); this is the one sanctioned long call.
        { timeoutMs: 120_000 },
      );
      setImportResult(res);
      setCsvText("");
      // roster sizes, health aggregates and the weak matrix all move
      void queryClient.invalidateQueries({ queryKey: ["teacher", "classrooms"] });
      void queryClient.invalidateQueries({ queryKey: ["teacher", "roster"] });
      void queryClient.invalidateQueries({ queryKey: ["teacher", "classAnalytics"] });
      void queryClient.invalidateQueries({ queryKey: ["teacher", "weak-matrix"] });
    } catch (err) {
      setMutationError(errText(err));
    } finally {
      setImportBusy(false);
    }
  }

  async function createSupportPlan(studentId: number) {
    if (spBusy) return;
    setSpBusy(true);
    setSpMsg(null);
    try {
      await post<SupportPlanRow>("/teacher/support-plans", {
        student_id: studentId,
      });
      void queryClient.invalidateQueries({
        queryKey: ["teacher", "support-plans"],
      });
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
    // The roster is derived state, recomputed whenever its inputs change.
    // detailId is deliberately absent: including it would rebuild the
    // map on every detail open/close, and the map is only read from.
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
        // Accuracy signal from the roster-scoped matrix (not grade-wide
        // analytics) so an empty class reads neutral, not polluted.
        (() => {
          if (!wm) return null;
          let asked = 0;
          let correct = 0;
          for (const s of wm.students) {
            for (const cell of Object.values(s.cells)) {
              asked += cell.asked;
              correct += cell.correct;
            }
          }
          return asked > 0 ? (100 * correct) / asked : null;
        })(),
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
        <Button variant="soft" size="sm" onClick={refresh}>
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
                <span
                  className={`health-dot ${HEALTH_DOT[classHealth]}`}
                  aria-hidden
                />{" "}
                {t(HEALTH_LABEL_KEY[classHealth])}
              </Badge>
            )}
          </div>
          <div className="stat-row section-gap-top">
            {/* Roster-scoped stats: an empty classroom shows zeros, not the
                grade-wide numbers (analytics is platform/grade-wide). */}
            <Stat value={roster.length} label={t("students")} />
            <Stat
              value={analytics ? analytics.chapters.length : 0}
              label={t("chapter")}
            />
            <Stat
              value={
                wm
                  ? new Set(
                      wm.students
                        .flatMap((s) => s.weak_concepts ?? [])
                        .filter(Boolean),
                    ).size
                  : 0
              }
              label={t("weakChapters")}
            />
          </div>
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
                          <span
                            className={`health-dot ${HEALTH_DOT[h]}`}
                            aria-hidden
                          />
                          <span className="visually-hidden">
                            {t(HEALTH_LABEL_KEY[h])}
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
