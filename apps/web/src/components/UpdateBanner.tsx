import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { getLang, onLangChange } from "../i18n";
import { applyUpdate, subscribeUpdate } from "../lib/serviceWorkerUpdate";

/**
 * PWA-02: "a new version is ready" banner. It appears only when an update is
 * genuinely waiting (see lib/serviceWorkerUpdate) and never reloads by itself,
 * so an in-progress quiz attempt or a streaming answer is not thrown away.
 */
const COPY: Record<"bn" | "en", { message: string; action: string }> = {
  bn: {
    message: "নতুন সংস্করণ প্রস্তুত — আপডেট করলে সর্বশেষ সংস্করণ পাবেন।",
    action: "এখনই আপডেট করুন",
  },
  en: {
    message: "A new version is ready — update to get the latest.",
    action: "Update now",
  },
};

export function UpdateBanner() {
  const [waiting, setWaiting] = useState(false);
  // Re-render on language switch; the copy is keyed by the active language.
  const [, setLangTick] = useState(0);

  useEffect(() => subscribeUpdate(setWaiting), []);
  useEffect(() => onLangChange(() => setLangTick((n) => n + 1)), []);

  if (!waiting) return null;
  const copy = COPY[getLang()];
  return (
    <div className="update-banner" role="status">
      <span className="update-banner-text">{copy.message}</span>
      <button
        type="button"
        className="btn btn-sm btn-primary"
        onClick={applyUpdate}
      >
        <RefreshCw size={14} aria-hidden /> {copy.action}
      </button>
    </div>
  );
}
