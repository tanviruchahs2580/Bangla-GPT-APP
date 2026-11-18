import { useQuery } from "@tanstack/react-query";
import { get } from "../../api";
import { friendlyError } from "../../errors";
import { ResponsiveTable } from "../../components/ResponsiveTable";
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
        <ResponsiveTable
          columns={[
            {
              id: "subject",
              header: t("admSubject"),
              cell: (v) => (
                <>
                  {v.subject} · {v.class_level}
                </>
              ),
            },
            {
              id: "chapter",
              header: t("admChapter"),
              cellClassName: "cell-wrap-sm",
              cell: (v) => v.chapter,
            },
            {
              id: "version",
              header: t("admVersion"),
              cell: (v) => `v${v.current_version} (${v.versions_total})`,
            },
            { id: "source", header: t("admSource"), cell: (v) => v.source },
            {
              id: "updated_by",
              header: t("email"),
              cellClassName: "cell-wrap-sm",
              cell: (v) => v.updated_by_email ?? "—",
            },
          ]}
          rows={versions}
          rowKey={(v) => `${v.subject}-${v.class_level}-${v.chapter}`}
        />
      )}
    </div>
  );
}
