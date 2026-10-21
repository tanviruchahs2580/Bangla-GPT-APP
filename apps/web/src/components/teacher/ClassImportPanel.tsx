/**
 * Classroom CSV import panel (G-19): the textarea, the bulk-deadline submit,
 * the busy hint and the per-row invite-code report.
 *
 * Extracted from `pages/teacher/ClassesPage.tsx` (file size / cohesion). The
 * panel owns no state: the page keeps `csvText`, `importBusy` and
 * `importResult` because the import runs through the page's request helper.
 */
import { Button, Card } from "../ui";
import { t } from "../../i18n";
import type { ImportResult } from "../../types";

export interface ClassImportPanelProps {
  csvText: string;
  onCsvText: (value: string) => void;
  importBusy: boolean;
  importResult: ImportResult | null;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}

export function ClassImportPanel({
  csvText,
  onCsvText,
  importBusy,
  importResult,
  onSubmit,
}: ClassImportPanelProps) {
  const rows = importResult?.rows.filter((row) => row.invite_code) ?? [];
  return (
    <Card title={t("csvImport")}>
      <p className="muted">{t("csvHint")}</p>
      <form onSubmit={onSubmit}>
        <textarea
          rows={5}
          className="textarea mono-block"
          value={csvText}
          onChange={(e) => onCsvText(e.target.value)}
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
      {importBusy && (
        <p className="muted" role="status">
          {t("importBusyHint")}
        </p>
      )}
      {importResult && (
        <div role="status">
          <p>
            <span>{t("importCreated", { n: importResult.created })}</span>
            {" · "}
            <span>{t("importFailed", { n: importResult.failed })}</span>
          </p>
          {rows.length > 0 && (
            <div className="table-wrap">
              <table className="data">
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.email}>
                      <td>{row.name}</td>
                      <td>{row.email}</td>
                      <td>
                        {t("inviteCode")}: <code>{row.invite_code}</code>
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
  );
}
