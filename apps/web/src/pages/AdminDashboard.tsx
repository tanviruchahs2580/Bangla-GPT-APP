import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  del,
  get,
  getFeedbackQueue,
  patch,
  post,
  startImpersonation,
  triageFeedback,
} from "../api";
import { friendlyError } from "../errors";
import { AiQualityCard } from "../components/admin/AiQualityCard";
import { t } from "../i18n";
import { roleLabel } from "../lib/roles";
import { useDebounced } from "../lib/useDebounced";
import { formatServerDateTime } from "../lib/datetime";
import type {
  AdminOverview,
  AdminSchoolStats,
  AdminUsersPage,
  ContentVersionRow,
  FeedbackQueuePage,
  RefusalAudit,
  SchoolInviteAdmin,
  UserPublic,
} from "../types";

// Every value RoleUpdateRequest accepts. school_admin was missing here, so the
// table rendered a school_admin row with the first option ("student") selected
// and offered no way back — saving any other edit on that row would demote them.
const ROLES = [
  "student",
  "teacher",
  "parent",
  "school_admin",
  "admin",
] as const;
const INVITE_ROLES = ["teacher", "school_admin"] as const;

function errOf(err: unknown): string {
  return (
    friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
    t("errorGeneric")
  );
}

export default function AdminDashboard() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [purgeMsg, setPurgeMsg] = useState<string | null>(null);
  const [purgeConfirming, setPurgeConfirming] = useState(false);
  const [purgeBusy, setPurgeBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const LIMIT = 20;

  // admin center -- schools + stats, invite management, content versions.
  const [invites, setInvites] = useState<SchoolInviteAdmin[]>([]);
  const [selSchool, setSelSchool] = useState<number | null>(null);
  const [schoolName, setSchoolName] = useState("");
  const [inviteRoles, setInviteRoles] = useState<Record<number, string>>({});
  const [inviteCode, setInviteCode] = useState<string | null>(null);
  const [admMsg, setAdmMsg] = useState<string | null>(null);

  // feedback triage queue + audited impersonation launch.
  const [triageStatus, setTriageStatus] = useState<"open" | "all">("open");
  const [queue, setQueue] = useState<FeedbackQueuePage | null>(null);
  const [triageErr, setTriageErr] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [triageMsg, setTriageMsg] = useState<string | null>(null);

  // F-023: the search box keys a DEBOUNCED query, so a typed burst fires one
  // request instead of five authenticated calls per keystroke (and a
  // superseded query string cannot settle late into the table).
  const debouncedQuery = useDebounced(query.trim(), 300);

  const usersQuery = useQuery({
    queryKey: ["admin-users", debouncedQuery, roleFilter, offset],
    queryFn: () => {
      const params: Record<string, string | number> = { limit: LIMIT, offset };
      if (debouncedQuery) params.q = debouncedQuery;
      if (roleFilter) params.role = roleFilter;
      const qs = new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)]),
      );
      return get<AdminUsersPage>(`/admin/users?${qs}`);
    },
  });
  const overviewQuery = useQuery({
    queryKey: ["admin-overview"],
    queryFn: () => get<AdminOverview>("/admin/analytics/overview"),
  });
  // center cards ride the same refresh; auxiliary on failure.
  const schoolsQuery = useQuery({
    queryKey: ["admin-schools"],
    queryFn: () =>
      get<AdminSchoolStats[]>("/admin/schools/stats").catch(() => []),
  });
  const versionsQuery = useQuery({
    queryKey: ["admin-versions"],
    queryFn: () =>
      get<ContentVersionRow[]>("/admin/content/versions").catch(() => []),
  });
  // The refusal card treats "no data yet" as loading (F-027, out of scope
  // here): preserve the swallow-to-null so a failure keeps that state.
  const refusalsQuery = useQuery({
    queryKey: ["admin-refusals"],
    queryFn: () =>
      get<RefusalAudit>("/admin/safety/refusals").catch(() => null),
  });

  const page = usersQuery.data ?? { total: 0, items: [] };
  const overview = overviewQuery.data ?? null;
  const schools = schoolsQuery.data ?? [];
  const versions = versionsQuery.data ?? [];
  const refusals = refusalsQuery.data ?? null;
  // A failed primary fetch must be visible, exactly as the old Promise.all
  // catch showed it.
  const loadError =
    usersQuery.isError || overviewQuery.isError
      ? errOf(usersQuery.error ?? overviewQuery.error)
      : null;

  /** Refresh the same set of queries the old load() re-fetched. */
  const refresh = useCallback(() => {
    for (const key of [
      "admin-users",
      "admin-overview",
      "admin-schools",
      "admin-versions",
      "admin-refusals",
    ]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  }, [queryClient]);

  const loadTriage = useCallback(() => {
    getFeedbackQueue(triageStatus)
      .then((page) => {
        setQueue(page);
        setTriageErr(null);
      })
      .catch((err: unknown) => {
        // Show the failure: leaving `queue` null renders "loading" forever,
        // which reads as a slow network and hides a broken triage queue.
        setQueue(null);
        setTriageErr(errOf(err));
      });
  }, [triageStatus]);

  useEffect(() => {
    loadTriage();
  }, [loadTriage]);

  async function doTriage(id: number, triaged: boolean) {
    setTriageMsg(null);
    try {
      const note = (notes[id] ?? "").trim();
      await triageFeedback(id, note ? { triaged, note } : { triaged });
      loadTriage();
    } catch (err) {
      setTriageMsg(errOf(err));
    }
  }

  async function doImpersonate(user: UserPublic) {
    const reason = window.prompt(t("impReasonPrompt"));
    if (reason === null || reason.trim().length < 3) return;
    try {
      await startImpersonation(user.id, reason.trim());
      // Full reload: every component (and the auth context) re-reads the
      // swapped token, and the shell shows the "support session" banner.
      window.location.assign("/");
    } catch (err) {
      setError(errOf(err));
    }
  }

  const loadInvites = useCallback(() => {
    if (selSchool === null) {
      setInvites([]);
      return;
    }
    get<SchoolInviteAdmin[]>(`/admin/schools/${selSchool}/invites`)
      .then((rows) => setInvites(rows))
      .catch(() => setInvites([]));
  }, [selSchool]);

  useEffect(() => {
    loadInvites();
  }, [loadInvites]);

  async function changeRole(user: UserPublic, role: string) {
    if (role === user.role) return;
    setError(null);
    try {
      await patch(`/admin/users/${user.id}/role`, { role });
      refresh();
    } catch (err) {
      setError(errOf(err));
    }
  }

  async function purge() {
    setPurgeMsg(null);
    setPurgeBusy(true);
    try {
      const res = await post<Record<string, number>>(
        "/admin/maintenance/purge",
      );
      setPurgeMsg(`${t("purged")}: ${JSON.stringify(res)}`);
      setPurgeConfirming(false);
    } catch (err) {
      setPurgeMsg(errOf(err));
    } finally {
      setPurgeBusy(false);
    }
  }

  async function addSchool(e: React.FormEvent) {
    e.preventDefault();
    if (schoolName.trim().length < 2) return;
    setError(null);
    try {
      await post("/admin/schools", { name: schoolName.trim() });
      setSchoolName("");
      refresh();
    } catch (err) {
      setError(errOf(err));
    }
  }

  async function createInvite(schoolId: number) {
    setAdmMsg(null);
    setInviteCode(null);
    try {
      const res = await post<{ code: string }>(`/schools/${schoolId}/invites`, {
        role: inviteRoles[schoolId] ?? "teacher",
      });
      setInviteCode(res.code);
      if (schoolId === selSchool) loadInvites();
    } catch (err) {
      setAdmMsg(errOf(err));
    }
  }

  async function revokeInvite(inviteId: number) {
    if (selSchool === null) return;
    setAdmMsg(null);
    try {
      await del(`/admin/schools/${selSchool}/invites/${inviteId}`);
      setAdmMsg(t("admRevoked"));
      loadInvites();
    } catch (err) {
      setAdmMsg(errOf(err));
    }
  }

  return (
    <>
      <h1 className="page-title">{t("adminDashboard")}</h1>

      <AiQualityCard />

      <div className="card">
        <h2>{t("maintenance")}</h2>
        {/* Two-step confirm, matching account deletion on MePage. This used to
            be one click that permanently purged expired tokens, invites and old
            chats server-side, with no warning, no busy state and no way back. */}
        {!purgeConfirming ? (
          <button
            className="secondary"
            onClick={() => setPurgeConfirming(true)}
          >
            {t("purgeExpired")}
          </button>
        ) : (
          <div className="stack">
            <p className="error m-0">{t("purgeConfirm")}</p>
            <div className="row-flex">
              <button
                className="secondary"
                onClick={purge}
                disabled={purgeBusy}
              >
                {t("purgeExpired")}
              </button>
              <button
                className="ghost"
                onClick={() => setPurgeConfirming(false)}
                disabled={purgeBusy}
              >
                {t("cancel")}
              </button>
            </div>
          </div>
        )}
        {purgeMsg && (
          <p className="muted" role="status">
            {purgeMsg}
          </p>
        )}
      </div>

      <div className="card">
        <h2>{t("adminDashboard")}</h2>
        {(error ?? loadError) && (
          <p className="error" role="alert">
            {error ?? loadError}
          </p>
        )}
        {overview && (
          <div className="stat-row">
            <div className="stat">
              <div className="num">{overview.users_total}</div>
              <div className="lbl">{t("statTotal")}</div>
            </div>
            <div className="stat">
              <div className="num">{overview.students}</div>
              <div className="lbl">{t("roleStudent")}</div>
            </div>
            <div className="stat">
              <div className="num">{overview.teachers}</div>
              <div className="lbl">{t("roleTeacher")}</div>
            </div>
            <div className="stat">
              <div className="num">{overview.parents}</div>
              <div className="lbl">{t("roleParent")}</div>
            </div>
            <div className="stat">
              <div className="num">{overview.quiz_attempts_graded}</div>
              <div className="lbl">{t("statQuizzes")}</div>
            </div>
          </div>
        )}
      </div>

      {/* refusal audit -- why/where safety refusals happened (counts only). */}
      <div className="card">
        <h2>{t("admSafety")}</h2>
        {refusals === null ? (
          <p className="muted" role="status">
            {t("loading")}
          </p>
        ) : (
          <>
            <div className="stat-row">
              <div className="stat">
                <div className="num">{refusals.total_refusals}</div>
                <div className="lbl">{t("admRefusals")}</div>
              </div>
            </div>
            {refusals.total_refusals === 0 ? (
              <p className="muted">{t("admNoRefusals")}</p>
            ) : (
              <>
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th scope="col">{t("admRefusalReason")}</th>
                        <th scope="col">{t("admRefusals")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(refusals.by_reason).map(([reason, n]) => (
                        <tr key={reason}>
                          <td>{reason}</td>
                          <td>{n}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted">
                  {Object.entries(refusals.by_class).map(([cls, n]) => (
                    <span key={cls} className="mr-2">
                      {`${t("admRefusalClass")} ${cls}: ${n}`}
                    </span>
                  ))}
                </p>
                {refusals.last_refusal_at && (
                  <p className="muted">
                    {t("admLastRefusal")}:{" "}
                    {formatServerDateTime(refusals.last_refusal_at)}
                  </p>
                )}
              </>
            )}
          </>
        )}
      </div>

      {/* feedback triage queue (reporter identity withheld, ). */}
      <div className="card">
        <h2>{t("admTriage")}</h2>
        <div className="row-flex gap-2 mb-2">
          <button
            className={
              triageStatus === "open" ? "primary small" : "secondary small"
            }
            onClick={() => setTriageStatus("open")}
          >
            {t("admTriageOpen")}
          </button>
          <button
            className={
              triageStatus === "all" ? "primary small" : "secondary small"
            }
            onClick={() => setTriageStatus("all")}
          >
            {t("admTriageAll")}
          </button>
          {queue && (
            <span className="muted">
              {t("admOpenCount", { n: queue.open_count, t: queue.total })}
            </span>
          )}
        </div>
        {triageMsg && (
          <p className="error" role="alert">
            {triageMsg}
          </p>
        )}
        {triageErr ? (
          <p className="error" role="alert">
            {triageErr}{" "}
            <button className="btn btn-sm btn-ghost" onClick={loadTriage}>
              {t("retry")}
            </button>
          </p>
        ) : queue === null ? (
          <p className="muted" role="status">
            {t("loading")}
          </p>
        ) : queue.rows.length === 0 ? (
          <p className="muted">{t("admNoFeedback")}</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">{t("role")}</th>
                  <th scope="col">±</th>
                  <th scope="col">{t("admNoteLabelShort")}</th>
                  <th scope="col">{t("admStatus")}</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {queue.rows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.id}</td>
                    <td>{roleLabel(row.role)}</td>
                    <td>{row.rating > 0 ? "+" : row.rating < 0 ? "−" : "·"}</td>
                    <td className="cell-wrap">
                      {row.comment ?? "—"}
                      {row.note && (
                        <div className="muted">
                          {t("admNoteLabel")}: {row.note}
                        </div>
                      )}
                    </td>
                    <td>
                      {row.triaged ? t("admTriaged") : t("admTriageOpen")}
                    </td>
                    <td>
                      <input
                        value={notes[row.id] ?? ""}
                        maxLength={500}
                        placeholder={t("admNoteLabel")}
                        aria-label={`${t("admNoteLabel")} #${row.id}`}
                        onChange={(e) =>
                          setNotes({ ...notes, [row.id]: e.target.value })
                        }
                      />{" "}
                      {row.triaged ? (
                        <button
                          className="small secondary"
                          onClick={() => doTriage(row.id, false)}
                        >
                          {t("admReopen")}
                        </button>
                      ) : (
                        <button
                          className="small primary"
                          onClick={() => doTriage(row.id, true)}
                        >
                          {t("admMarkTriage")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2>{t("admSchools")}</h2>
        <form onSubmit={addSchool}>
          <label htmlFor="nschool">{t("admNewSchool")}</label>
          <input
            id="nschool"
            value={schoolName}
            onChange={(e) => setSchoolName(e.target.value)}
            minLength={2}
            maxLength={200}
            required
          />
          <button className="primary small" type="submit">
            {t("admCreateSchool")}
          </button>
        </form>
        {inviteCode && (
          <p role="status">
            {t("admInviteOnce")} <code>{inviteCode}</code>
          </p>
        )}
        {admMsg && (
          <p className="muted" role="status">
            {admMsg}
          </p>
        )}
        {schools.length === 0 ? (
          <p className="muted">{t("admNoSchools")}</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{t("admNewSchool")}</th>
                  <th scope="col">{t("admCode")}</th>
                  <th scope="col">{t("sdTeachers")}</th>
                  <th scope="col">{t("admClassrooms")}</th>
                  <th scope="col">{t("students")}</th>
                  <th scope="col">{t("admSessions7d")}</th>
                  <th scope="col">{t("admInvite")}</th>
                </tr>
              </thead>
              <tbody>
                {schools.map((s) => (
                  <tr key={s.id}>
                    <td className="cell-wrap-sm">
                      <button
                        className="small secondary"
                        onClick={() =>
                          setSelSchool(s.id === selSchool ? null : s.id)
                        }
                        aria-label={`${s.name} ${t("admInvites")}`}
                      >
                        {s.name}
                      </button>
                    </td>
                    <td>{s.code}</td>
                    <td>{s.teachers}</td>
                    <td>{s.classrooms}</td>
                    <td>{s.students}</td>
                    <td>{s.sessions_7d}</td>
                    <td>
                      <select
                        value={inviteRoles[s.id] ?? "teacher"}
                        onChange={(e) =>
                          setInviteRoles({
                            ...inviteRoles,
                            [s.id]: e.target.value,
                          })
                        }
                        aria-label={`${s.name} ${t("role")}`}
                      >
                        {INVITE_ROLES.map((r) => (
                          <option key={r} value={r}>
                            {roleLabel(r)}
                          </option>
                        ))}
                      </select>{" "}
                      <button
                        className="small primary"
                        onClick={() => createInvite(s.id)}
                      >
                        {t("admInvite")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {selSchool !== null && (
          <div className="table-wrap">
            <table className="data">
              <caption>{t("admInvites")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("role")}</th>
                  <th scope="col">{t("admStatus")}</th>
                  <th scope="col">{t("admCreated")}</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {invites.map((i) => (
                  <tr key={i.id}>
                    <td>{roleLabel(i.role)}</td>
                    <td>{i.used ? t("admUsed") : t("admActive")}</td>
                    <td>{i.created_at.slice(0, 10)}</td>
                    <td>
                      {!i.used && (
                        <button
                          className="small secondary"
                          onClick={() => revokeInvite(i.id)}
                        >
                          {t("admRevoke")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2>{t("admVersions")}</h2>
        {versions.length === 0 ? (
          <p className="muted">{t("admNoVersions")}</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{t("admSubject")}</th>
                  <th scope="col">{t("admChapter")}</th>
                  <th scope="col">{t("admVersion")}</th>
                  <th scope="col">{t("admSource")}</th>
                  <th scope="col">{t("email")}</th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={`${v.subject}-${v.class_level}-${v.chapter}`}>
                    <td>
                      {v.subject} · {v.class_level}
                    </td>
                    <td className="cell-wrap-sm">{v.chapter}</td>
                    <td>
                      v{v.current_version} ({v.versions_total})
                    </td>
                    <td>{v.source}</td>
                    <td className="cell-wrap-sm">
                      {v.updated_by_email ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2>{t("searchEmail")}</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setOffset(0);
            refresh();
          }}
        >
          <label htmlFor="q">{t("searchEmail")}</label>
          <input
            id="q"
            value={query}
            placeholder={t("searchEmail")}
            onChange={(e) => {
              setQuery(e.target.value);
              // Typing IS a new search: the debounced query sits in the query
              // key, so the request goes out without a submit. Keeping the old
              // offset sent `?q=…&offset=20` from page 2 onwards and the table
              // rendered zero rows — a search reporting "no such user" for
              // users who exist.
              setOffset(0);
            }}
          />
          <label htmlFor="rfilter">{t("role")}</label>
          <select
            id="rfilter"
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">—</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </select>
          <button className="primary small" type="submit">
            {t("send")}
          </button>
        </form>

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">{t("email")}</th>
                <th scope="col">{t("role")}</th>
                <th scope="col"></th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((u) => (
                <tr key={u.id}>
                  <td>{u.id}</td>
                  <td className="cell-wrap-sm">{u.email}</td>
                  <td>{roleLabel(u.role)}</td>
                  <td>
                    <select
                      value={u.role}
                      onChange={(e) => changeRole(u, e.target.value)}
                      aria-label={`${u.email} ${t("role")}`}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {roleLabel(r)}
                        </option>
                      ))}
                    </select>{" "}
                    {/* server refuses admin targets; button mirrors that. */}
                    {u.role !== "admin" && u.role !== "school_admin" && (
                      <button
                        className="small secondary"
                        onClick={() => doImpersonate(u)}
                      >
                        {t("impersonate")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted">
          {page.total} — {offset + 1}–{Math.min(offset + LIMIT, page.total)}{" "}
          <button
            className="small secondary"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - LIMIT))}
          >
            ‹
          </button>{" "}
          <button
            className="small secondary"
            disabled={offset + LIMIT >= page.total}
            onClick={() => setOffset(offset + LIMIT)}
          >
            ›
          </button>
        </p>
      </div>
    </>
  );
}
