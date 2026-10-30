import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { del, get, post } from "../../api";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";
import { roleLabel } from "../../lib/roles";
import type { AdminSchoolStats, SchoolInviteAdmin } from "../../types";
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
      return;
    }
    get<SchoolInviteAdmin[]>(`/admin/schools/${selSchool}/invites`)
      .then((rows) => setInvites(rows))
      .catch(() => setInvites([]));
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
  );
}
