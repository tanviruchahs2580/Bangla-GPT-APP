import { useQuery } from "@tanstack/react-query";
import { get } from "../../api";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";
import type { ContentVersionRow } from "../../types";
import { LoadError } from "../ui";

/** F-094 split: the content-versions card with its own query. */
export function VersionsCard() {
  const versionsQuery = useQuery({
    queryKey: ["admin-versions"],
    queryFn: () => get<ContentVersionRow[]>("/admin/content/versions"),
  });
  const versions = versionsQuery.data ?? [];
  return (
    <div className="card">
      <h2>{t("admVersions")}</h2>
      {versionsQuery.isError ? (
        <LoadError
          message={
            friendlyError(
              (versionsQuery.error as { rawDetail?: unknown }).rawDetail,
            )?.text ?? t("errorGeneric")
          }
          onRetry={() => void versionsQuery.refetch()}
        />
      ) : versions.length === 0 ? (
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
                  <td className="cell-wrap-sm">{v.updated_by_email ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
