import { useCallback, useEffect, useState } from "react";
import { getFeedbackQueue, triageFeedback } from "../../api";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";
import { roleLabel } from "../../lib/roles";
import type { FeedbackQueuePage } from "../../types";

/**
 * F-094 split: the feedback-triage card, extracted from AdminDashboard with
 * its state and fetch loop. Reporter identity stays withheld (the API sends
 * role only) and a failed queue load keeps the retryable error state.
 */
function errOf(err: unknown): string {
  return (
    friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
    t("errorGeneric")
  );
}

export function FeedbackQueueCard() {
  const [triageStatus, setTriageStatus] = useState<"open" | "all">("open");
  const [queue, setQueue] = useState<FeedbackQueuePage | null>(null);
  const [triageErr, setTriageErr] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [triageMsg, setTriageMsg] = useState<string | null>(null);

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

  return (
    // feedback triage queue (reporter identity withheld, ).
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
          <button
            className="btn btn-sm btn-ghost"
            onClick={loadTriage}
            aria-label={`${t("admTriage")} — ${t("retry")}`}
          >
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
                  <td>{row.triaged ? t("admTriaged") : t("admTriageOpen")}</td>
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
  );
}
