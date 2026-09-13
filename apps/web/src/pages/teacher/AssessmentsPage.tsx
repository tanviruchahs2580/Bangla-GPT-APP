import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { get, post } from "../../api";
import type {
  AssignmentProgressRow,
  AssignmentRow,
  ClassRoom,
  QPaper,
  RosterEntry,
} from "../../types";
import { Badge, Button, Card, Stat } from "../../components/ui";
import { QPaperReviewPanel } from "../../components/teacher/QPaperReviewPanel";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";
import { cn } from "../../lib/cn";

const errText = (err: unknown): string =>
  friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
  t("errorGeneric");

type Tab = "papers" | "shorttests" | "assignments";

export default function AssessmentsPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab | null) ?? "papers";

  const [rooms, setRooms] = useState<ClassRoom[]>([]);
  const [roomId, setRoomId] = useState<number | null>(null);
  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  // QP library + selected review target.
  const [qps, setQps] = useState<QPaper[]>([]);
  const [openQp, setOpenQp] = useState<QPaper | null>(null);

  // C16 per-student quiz assignment (roster row action).
  const [assignTo, setAssignTo] = useState<number | null>(null);
  const [assignSubject, setAssignSubject] = useState("science");
  const [assignCount, setAssignCount] = useState(5);
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignMsg, setAssignMsg] = useState<string | null>(null);

  // S2.8 bulk assignment.
  const [selIds, setSelIds] = useState<Set<number>>(new Set());
  const [asChapter, setAsChapter] = useState("");
  const [asSubject, setAsSubject] = useState("science");
  const [asCount, setAsCount] = useState(5);
  const [asDue, setAsDue] = useState("");
  const [asBusy, setAsBusy] = useState(false);
  const [asMsg, setAsMsg] = useState<string | null>(null);
  const [assigns, setAssigns] = useState<AssignmentRow[]>([]);
  const [asProg, setAsProg] = useState<Record<number, AssignmentProgressRow[]>>(
    {},
  );
  const [asOpen, setAsOpen] = useState<number | null>(null);

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
      setSelIds(new Set());
      return;
    }
    setError(null);
    Promise.all([
      get<RosterEntry[]>(`/teacher/classrooms/${roomId}/roster`),
      get<AssignmentRow[]>("/teacher/assignments").catch(() => []),
    ])
      .then(([r, rows]) => {
        setRoster(r);
        setAssigns(rows ?? []);
        setSelIds(new Set());
        setAsOpen(null);
        setAsProg({});
      })
      .catch((err: unknown) => setError(errText(err)));
  }, [roomId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let live = true;
    get<QPaper[]>("/teacher/qpapers")
      .then((rows) => {
        if (live) setQps(rows ?? []);
      })
      .catch(() => {
        if (live) setQps([]);
      });
    return () => {
      live = false;
    };
  }, []);

  async function assignQuiz(e: React.FormEvent) {
    e.preventDefault();
    if (assignTo === null || assignBusy || selected === null) return;
    setAssignBusy(true);
    setAssignMsg(null);
    try {
      const started = await post<{ attempt_id: number }>("/quizzes", {
        student_id: assignTo,
        class_level: selected.class_level,
        subject: assignSubject,
        num_questions: assignCount,
      });
      setAssignMsg(t("assigned", { id: started.attempt_id }));
    } catch (err) {
      setAssignMsg(errText(err));
    } finally {
      setAssignBusy(false);
    }
  }

  function toggleSel(id: number) {
    setSelIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const allSelected =
    roster.length > 0 && roster.every((s) => selIds.has(s.student_id));

  function toggleAllSel() {
    setSelIds(
      allSelected ? new Set() : new Set(roster.map((s) => s.student_id)),
    );
  }

  async function assignBulk(e: React.FormEvent) {
    e.preventDefault();
    if (asBusy || selIds.size === 0 || !asChapter.trim() || !asDue) return;
    setAsBusy(true);
    setAsMsg(null);
    try {
      const row = await post<AssignmentRow>("/teacher/assignments", {
        student_ids: [...selIds],
        subject: asSubject,
        chapter: asChapter.trim(),
        num_questions: asCount,
        due_at: asDue,
      });
      setAssigns((ls) => [row, ...ls]);
      setSelIds(new Set());
      setAsMsg(t("baSelected", { n: row.attempts.length }));
    } catch (err) {
      setAsMsg(errText(err));
    } finally {
      setAsBusy(false);
    }
  }

  async function toggleProgress(id: number) {
    if (asOpen === id) {
      setAsOpen(null);
      return;
    }
    setAsOpen(id);
    if (asProg[id]) return;
    try {
      const rows = await get<AssignmentProgressRow[]>(
        `/teacher/assignments/${id}/progress`,
      );
      setAsProg((m) => ({ ...m, [id]: rows }));
    } catch (err) {
      setAsMsg(errText(err));
    }
  }

  const TABS: Array<{ id: Tab; label: string }> = [
    { id: "papers", label: t("asmTabPapers") },
    { id: "shorttests", label: t("asmTabShortTests") },
    { id: "assignments", label: t("asmTabAssignments") },
  ];

  return (
    <main className="shell-main">
      <section className="section-head">
        <h1 className="page-title">{t("asmTitle")}</h1>
      </section>

      <div
        className="chips chips-gap"
        role="tablist"
        aria-label={t("asmTitle")}
      >
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={cn("chip", tab === id && "active")}
            onClick={() => setParams({ tab: id })}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {/* ── question papers ── */}
      {tab === "papers" && (
        <>
          {openQp ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setOpenQp(null)}
                aria-label={t("back")}
              >
                ← {t("back")}
              </Button>
              <QPaperReviewPanel
                qp={openQp}
                onChange={(next) => {
                  setOpenQp(next);
                  setQps((list) =>
                    list.map((q) => (q.id === next.id ? next : q)),
                  );
                }}
              />
            </>
          ) : (
            <Card title={t("asmTabPapers")}>
              <p className="muted muted-sm">{t("asmCreateInCreate")}</p>
              {qps.length === 0 ? (
                <p className="muted">{t("noDocumentsYet")}</p>
              ) : (
                <div className="stack">
                  {qps.map((qp) => (
                    <div key={qp.id} className="row qp-review-row">
                      <span className="quick-icon tile-teal" aria-hidden>
                        {qp.status === "final" ? "✓" : "✎"}
                      </span>
                      <div className="row-main">
                        <div className="row-title">
                          {qp.exam_type || t("qpTitle")} — {qp.subject} ·{" "}
                          {t("classLabel")} {qp.class_level}
                        </div>
                        <div className="row-sub">
                          {qp.questions.length}Q · {qp.marks} {t("qpMarks")} ·{" "}
                          {qp.questions.filter((q) => q.reviewed).length}/
                          {qp.questions.length} {t("stepApprove")}
                        </div>
                      </div>
                      <Badge tone={qp.status === "final" ? "ok" : "teal"}>
                        {qp.status === "final"
                          ? t("qpFinalized")
                          : t("qpNeedsReview")}
                      </Badge>
                      <Button
                        variant="soft"
                        size="sm"
                        onClick={() => setOpenQp(qp)}
                      >
                        {t("cOpen")}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}
        </>
      )}

      {/* ── short tests ── */}
      {tab === "shorttests" && (
        <Card title={t("asmTabShortTests")}>
          <p className="muted muted-sm">{t("asmCreateInCreate")}</p>
          <ShortTestList />
        </Card>
      )}

      {/* ── bulk assignments + per-student quiz assignment ── */}
      {tab === "assignments" && (
        <>
          <div className="card">
            <div className="row-flex gap-2">
              {rooms.map((r) => (
                <button
                  key={r.id}
                  className={`chip${r.id === roomId ? " active" : ""}`}
                  aria-pressed={r.id === roomId}
                  onClick={() => setRoomId(r.id)}
                >
                  {t("className").replace(/\s*\(.*\)/, "")} {r.class_level} ·{" "}
                  {r.section} ({r.student_count})
                </button>
              ))}
              {rooms.length === 0 && <p className="muted">{t("noStudents")}</p>}
            </div>
          </div>

          <Card title={t("classStudents")}>
            {roster.length === 0 ? (
              <p className="muted">{t("noStudents")}</p>
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">
                        <input
                          type="checkbox"
                          aria-label={t("baSelect")}
                          checked={allSelected}
                          onChange={toggleAllSel}
                        />
                      </th>
                      <th scope="col">#</th>
                      <th scope="col">{t("name")}</th>
                      <th scope="col">{t("quizTitle")}</th>
                      <th scope="col">{t("avgScore")}</th>
                      <th scope="col"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {roster.map((s) => (
                      <tr key={s.student_id}>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`${t("baSelect")}: ${s.name}`}
                            checked={selIds.has(s.student_id)}
                            onChange={() => toggleSel(s.student_id)}
                          />
                        </td>
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
                        <td>{s.attempts_graded}</td>
                        <td>
                          {s.avg_score_pct === null
                            ? "—"
                            : `${s.avg_score_pct}%`}
                        </td>
                        <td>
                          <Button
                            variant={
                              assignTo === s.student_id ? "primary" : "soft"
                            }
                            size="sm"
                            onClick={() => setAssignTo(s.student_id)}
                          >
                            {t("assignQuiz")}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title={t("baTitle")}>
            <form onSubmit={assignBulk} className="row-flex gap-2">
              <label htmlFor="bachap">{t("baChapterLabel")}</label>
              <input
                id="bachap"
                value={asChapter}
                onChange={(e) => setAsChapter(e.target.value)}
                className="input w-min-field"
              />
              <label htmlFor="basubj">{t("subject")}</label>
              <select
                id="basubj"
                className="select"
                value={asSubject}
                onChange={(e) => setAsSubject(e.target.value)}
              >
                <option value="science">{t("subjectScience")}</option>
                <option value="math">{t("subjectMath")}</option>
                <option value="bangla">{t("subjectBangla")}</option>
              </select>
              <label htmlFor="bacount">{t("questionCount")}</label>
              <input
                id="bacount"
                type="number"
                min={3}
                max={25}
                value={asCount}
                onChange={(e) => setAsCount(Number(e.target.value) || 5)}
                className="input w-num"
              />
              <label htmlFor="badue">{t("baDue")}</label>
              <input
                id="badue"
                className="input"
                type="datetime-local"
                value={asDue}
                onChange={(e) => setAsDue(e.target.value)}
              />
              <button
                className="primary"
                disabled={
                  asBusy || selIds.size === 0 || !asChapter.trim() || !asDue
                }
              >
                {t("baAssign")} ({t("baSelected", { n: selIds.size })})
              </button>
            </form>
            {asMsg && <p className="muted">{asMsg}</p>}
          </Card>

          {assignTo !== null && (
            <Card title={`${t("assignQuiz")} · #${assignTo}`}>
              <form onSubmit={assignQuiz} className="grid-2">
                <div>
                  <label htmlFor="asubj">{t("subject")}</label>
                  <select
                    id="asubj"
                    className="select"
                    value={assignSubject}
                    onChange={(e) => setAssignSubject(e.target.value)}
                  >
                    <option value="science">{t("subjectScience")}</option>
                    <option value="math">{t("subjectMath")}</option>
                    <option value="bangla">{t("subjectBangla")}</option>
                  </select>
                  <label htmlFor="acount">{t("questionCount")}</label>
                  <input
                    id="acount"
                    className="input"
                    type="number"
                    min={1}
                    max={10}
                    value={assignCount}
                    onChange={(e) => setAssignCount(Number(e.target.value))}
                  />
                </div>
                <div className="align-end">
                  <Button variant="primary" type="submit" loading={assignBusy}>
                    {t("assignQuiz")}
                  </Button>
                  {assignMsg && (
                    <p
                      className={assignMsg.includes("#") ? "ok" : "error"}
                      role="status"
                    >
                      {assignMsg}
                    </p>
                  )}
                </div>
              </form>
            </Card>
          )}

          <Card title={t("asmResults")}>
            {assigns.length === 0 ? (
              <p className="muted">{t("baNone")}</p>
            ) : (
              <div className="stack">
                {assigns.slice(0, 8).map((a) => (
                  <div key={a.id} className="as-result-row">
                    <div className="row-flex chips-gap">
                      <strong>{a.chapter}</strong>
                      <span className="muted muted-sm">
                        {a.subject} ·{" "}
                        {t("baSelected", { n: a.attempts.length })} ·{" "}
                        {t("baDue")}: {new Date(a.due_at).toLocaleString()}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggleProgress(a.id)}
                      >
                        {t("baProgress")}
                      </Button>
                    </div>
                    {asOpen === a.id && asProg[a.id] && (
                      <AssignmentResult rows={asProg[a.id]} />
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </main>
  );
}

/** Result summary from existing progress rows: avg / high / low + table. */
function AssignmentResult({ rows }: { rows: AssignmentProgressRow[] }) {
  const graded = rows.filter((r) => r.score_pct !== null);
  const scores = graded.map((r) => r.score_pct as number);
  const avg =
    scores.length > 0
      ? Math.round(scores.reduce((s, v) => s + v, 0) / scores.length)
      : null;
  return (
    <div className="stack section-gap-top">
      <p className="muted muted-sm m-0">
        {t("resCount", { n: graded.length })}
      </p>
      <div className="stat-row">
        <Stat value={avg === null ? "—" : `${avg}%`} label={t("resAvg")} />
        <Stat
          value={scores.length ? `${Math.round(Math.max(...scores))}%` : "—"}
          label={t("resHigh")}
        />
        <Stat
          value={scores.length ? `${Math.round(Math.min(...scores))}%` : "—"}
          label={t("resLow")}
        />
      </div>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">{t("name")}</th>
              <th scope="col">{t("baStatus")}</th>
              <th scope="col">{t("avgScore")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.attempt_id}>
                <td>{r.name}</td>
                <td>
                  {r.done ? (
                    <span className="badge badge-ok"> {t("baDone")}</span>
                  ) : r.overdue ? (
                    <span className="badge badge-warn"> {t("baOverdue")}</span>
                  ) : (
                    <span className="badge"> {t("baPending")}</span>
                  )}
                </td>
                <td>
                  {r.score_pct === null ? "·" : `${Math.round(r.score_pct)}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Short-test list (read-only here; creation lives in Create). */
function ShortTestList() {
  const [rows, setRows] = useState<
    Array<{
      id: number;
      chapter: string;
      subject: string;
      questions: unknown[];
      attempts: unknown[];
    }>
  >([]);
  useEffect(() => {
    let live = true;
    get("/teacher/shorttests")
      .then((r) => {
        if (live) setRows((r as typeof rows) ?? []);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  if (rows.length === 0) return <p className="muted">{t("stEmpty")}</p>;
  return (
    <ul>
      {rows.slice(0, 8).map((st) => (
        <li key={st.id}>
          {st.chapter} · {st.subject} · {st.questions.length}Q ·{" "}
          {t("stAssigned", { n: st.attempts.length })}
        </li>
      ))}
    </ul>
  );
}
