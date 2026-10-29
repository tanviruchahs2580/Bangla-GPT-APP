import { useCallback, useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { Card } from "./ui";
import { t } from "../i18n";
import {
  deleteChapter,
  downloadedChapters,
  offlineUsage,
  type OfflineChapter,
  type OfflineUsage,
} from "../lib/offlineStore";

/**
 * PWA-03: the student can see and free the space their offline copies use.
 * Before this the copies were unmanaged: they filled IndexedDB silently and
 * only a logout (or clearing site data) could remove one.
 *
 * The card renders nothing while there is nothing saved, so the normal
 * online path is unchanged.
 */
export function OfflineLibrary({
  userId,
  onOpen,
}: {
  userId: number;
  onOpen: (rec: OfflineChapter) => void;
}) {
  const [records, setRecords] = useState<OfflineChapter[]>([]);
  const [usage, setUsage] = useState<OfflineUsage | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRecords(await downloadedChapters(userId));
      setUsage(await offlineUsage(userId));
    } catch {
      /* storage unavailable: the section simply stays hidden */
    }
  }, [userId]);

  useEffect(() => {
    void refresh();
    return () => {
      // A stale list must not survive the user switching on a shared device.
      setRecords([]);
      setUsage(null);
    };
  }, [refresh]);

  const remove = async (rec: OfflineChapter) => {
    try {
      await deleteChapter(rec.userId, rec.subject, rec.chapter, rec.classLevel);
    } catch {
      /* the row stays; the student can retry */
    }
    await refresh();
  };

  if (records.length === 0) return null;
  return (
    <Card>
      <div className="card-title">
        {t("offlineBadge")} · {records.length}
        {usage ? ` · ${formatBytes(usage.bytes)}` : ""}
      </div>
      <div className="stack">
        {records.map((rec) => (
          <div key={rec.key} className="row-flex">
            <div className="row-main">
              <div className="row-title">{rec.chapter}</div>
              <div className="row-sub">
                {rec.subject} · {t("classLabel")} {rec.classLevel} ·{" "}
                {formatBytes(rec.bytes)}
              </div>
            </div>
            <button
              className="btn btn-soft btn-sm"
              onClick={() => onOpen(rec)}
              aria-label={`${t("readConcept")}: ${rec.chapter}`}
            >
              {t("readConcept")}
            </button>
            <button
              className="icon-btn"
              onClick={() => void remove(rec)}
              aria-label={`${t("deleteGeneric")}: ${rec.chapter}`}
            >
              <Trash2 size={16} aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Binary units: a device-storage figure must not read as network speed. */
function formatBytes(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MiB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KiB`;
  return `${bytes} B`;
}
