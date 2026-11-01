import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post, startImpersonation } from "../api";
import { friendlyError } from "../errors";
import { AiQualityCard } from "../components/admin/AiQualityCard";
import { FeedbackQueueCard } from "../components/admin/FeedbackQueueCard";
import { RefusalAuditCard } from "../components/admin/RefusalAuditCard";
import { SchoolsCard } from "../components/admin/SchoolsCard";
import { VersionsCard } from "../components/admin/VersionsCard";
import { t } from "../i18n";
import { roleLabel } from "../lib/roles";
import { useDebounced } from "../lib/useDebounced";
import type { AdminOverview, AdminUsersPage, UserPublic } from "../types";

/**
 * F-094 split: the schools/invites, feedback-triage, refusal-audit and
 * content-version cards live under components/admin/ now, each owning its
 * state and fetch. This file keeps the overview, the maintenance action and
 * the user table (the one card whose query key the page's refresh shares).
 */

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

  const page = usersQuery.data ?? { total: 0, items: [] };
  const overview = overviewQuery.data ?? null;
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
        "/admin/maintenance/purge?confirm=true",
      );
      const parts = Object.entries(res)
        .map(([key, n]) => `${key}: ${n}`)
        .join(", ");
      setPurgeMsg(`${t("purged")} — ${parts}`);
      setPurgeConfirming(false);
    } catch (err) {
      setPurgeMsg(errOf(err));
    } finally {
      setPurgeBusy(false);
    }
  }

  return (
    /* A11Y-01: the staff layout had no <main> at all, so the route had no
       landmark and the shell's skip link had nothing to jump to. */
    <main id="main-content" tabIndex={-1} className="shell-main">
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

      <RefusalAuditCard />

      <FeedbackQueueCard />

      <SchoolsCard onChanged={refresh} onError={setError} />

      <VersionsCard />

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
            aria-label={t("prevPage")}
            onClick={() => setOffset(Math.max(0, offset - LIMIT))}
          >
            ‹
          </button>{" "}
          <button
            className="small secondary"
            disabled={offset + LIMIT >= page.total}
            aria-label={t("nextPage")}
            onClick={() => setOffset(offset + LIMIT)}
          >
            ›
          </button>
        </p>
      </div>
    </main>
  );
}
