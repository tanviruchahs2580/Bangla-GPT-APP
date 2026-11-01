import { useQuery } from "@tanstack/react-query";
import { get } from "../../api";
import { t } from "../../i18n";
import { formatServerDateTime } from "../../lib/datetime";
import type { RefusalAudit } from "../../types";

/**
 * F-094 split: the refusal-audit card, self-contained (query included) so
 * AdminDashboard keeps only the orchestration. Query key and failure posture
 * are unchanged: a failed fetch keeps rendering the loading state (F-027).
 */
export function RefusalAuditCard() {
  const refusalsQuery = useQuery({
    queryKey: ["admin-refusals"],
    queryFn: () =>
      get<RefusalAudit>("/admin/safety/refusals").catch(() => null),
  });
  const refusals = refusalsQuery.data ?? null;
  return (
    // refusal audit -- why/where safety refusals happened (counts only).
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
  );
}
