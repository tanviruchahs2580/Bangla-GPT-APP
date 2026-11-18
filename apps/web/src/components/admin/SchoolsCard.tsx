import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { del, get, post } from "../../api";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";
import { roleLabel } from "../../lib/roles";
import type {
  AdminSchoolStats,
  SchoolInviteAdmin,
  SchoolInviteOut,
} from "../../types";
import { ResponsiveTable } from "../ResponsiveTable";
import { LoadError } from "../ui";

/**
 * F-094 split: the schools + invites card, extracted from AdminDashboard
 * with its state, query and handlers. `onChanged` is the page's refresh()
 * (it invalidates the sibling admin queries exactly as a school creation
 * did before the split).
 */
const INVITE_ROLES = ["teacher", "school_admin"] as const;

function errOf(err: unknown): string {
  return (
    friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
    t("errorGeneric")
  );
}

export function SchoolsCard({
  onChanged,
  onError,
}: {
  onChanged: () => void;
  onError: (message: string | null) => void;
}) {
  const [invites, setInvites] = useState<SchoolInviteAdmin[]>([]);
  const [invitesFailed, setInvitesFailed] = useState(false);
  const [selSchool, setSelSchool] = useState<number | null>(null);
  const [schoolName, setSchoolName] = useState("");
  const [inviteRoles, setInviteRoles] = useState<Record<number, string>>({});
  const [inviteCode, setInviteCode] = useState<string | null>(null);
  const [admMsg, setAdmMsg] = useState<string | null>(null);

  const schoolsQuery = useQuery({
    queryKey: ["admin-schools"],
    queryFn: () => get<AdminSchoolStats[]>("/admin/schools/stats"),
  });
  const schools = schoolsQuery.data ?? [];

  const loadInvites = useCallback(() => {
    if (selSchool === null) {
      setInvites([]);
      setInvitesFailed(false);
      return;
    }
    // F-2xx: this used to `.catch(() => setInvites([]))`, so a failed request
    // rendered an empty invite table -- indistinguishable from "this school has
    // no invites". An admin would conclude there was nothing to revoke while
    // reading a lie. Every other loader in the product reports through
    // LoadError; this one now does too.
    get<SchoolInviteAdmin[]>(`/admin/schools/${selSchool}/invites`)
      .then((rows) => {
        setInvites(rows);
        setInvitesFailed(false);
      })
      .catch(() => {
        setInvites([]);
        setInvitesFailed(true);
      });
  }, [selSchool]);

  useEffect(() => {
    loadInvites();
  }, [loadInvites]);

  async function addSchool(e: React.FormEvent) {
    e.preventDefault();
    if (schoolName.trim().length < 2) return;
    // The page-level alert, exactly where a failed school creation reported
    // before the split (invite errors keep using this card's admMsg).
    onError(null);
    try {
      await post("/admin/schools", { name: schoolName.trim() });
      setSchoolName("");
      onChanged();
    } catch (err) {
      onError(errOf(err));
    }
  }

  async function createInvite(schoolId: number) {
    setAdmMsg(null);
    setInviteCode(null);
    try {
      const res = await post<SchoolInviteOut>(`/schools/${schoolId}/invites`, {
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
      {schoolsQuery.isError ? (
        <LoadError
          message={errOf(schoolsQuery.error)}
          onRetry={() => void schoolsQuery.refetch()}
        />
      ) : schools.length === 0 ? (
        <p className="muted">{t("admNoSchools")}</p>
      ) : (
        <ResponsiveTable
          columns={[
            {
              id: "name",
              header: t("admNewSchool"),
              cellClassName: "cell-wrap-sm",
              cell: (s) => (
                <button
                  className="small secondary"
                  onClick={() => setSelSchool(s.id === selSchool ? null : s.id)}
                  aria-label={`${s.name} ${t("admInvites")}`}
                >
                  {s.name}
                </button>
              ),
            },
            { id: "code", header: t("admCode"), cell: (s) => s.code },
            {
              id: "teachers",
              header: t("sdTeachers"),
              cell: (s) => s.teachers,
            },
            {
              id: "classrooms",
              header: t("admClassrooms"),
              cell: (s) => s.classrooms,
            },
            { id: "students", header: t("students"), cell: (s) => s.students },
            {
              id: "sessions",
              header: t("admSessions7d"),
              cell: (s) => s.sessions_7d,
            },
          ]}
          rows={schools}
          rowKey={(s) => String(s.id)}
          actions={(s) => (
            <>
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
            </>
          )}
        />
      )}
      {selSchool !== null && (
        <ResponsiveTable
          caption={t("admInvites")}
          columns={[
            { id: "role", header: t("role"), cell: (i) => roleLabel(i.role) },
            {
              id: "status",
              header: t("admStatus"),
              cell: (i) => (i.used ? t("admUsed") : t("admActive")),
            },
            {
              id: "created",
              header: t("admCreated"),
              cell: (i) => i.created_at.slice(0, 10),
            },
          ]}
          rows={invitesFailed ? [] : invites}
          rowKey={(i) => String(i.id)}
          tbodyPrefix={
            invitesFailed ? (
              <tr>
                <td colSpan={4}>
                  <LoadError onRetry={loadInvites} />
                </td>
              </tr>
            ) : null
          }
          actions={(i) =>
            !i.used ? (
              <button
                className="small secondary"
                onClick={() => revokeInvite(i.id)}
              >
                {t("admRevoke")}
              </button>
            ) : null
          }
        />
      )}
    </div>
  );
}
