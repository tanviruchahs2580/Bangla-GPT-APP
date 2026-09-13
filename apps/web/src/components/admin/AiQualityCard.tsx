import { useEffect, useState } from "react";
import { get } from "../../api";
import type { AdminAiQuality } from "../../api";
import { Badge } from "../ui";
import { t } from "../../i18n";
import { track } from "../../lib/analytics";

/** Wave 2 (blueprint §admin): AI answer-quality panel — grounding rate,
 * refusal breakdown, feedback thumbs, low-confidence count, per-model mix.
 * Manual fetch (AdminDashboard house style: no QueryClient dependency). */
export function AiQualityCard() {
  const [q, setQ] = useState<AdminAiQuality | null>(null);
  useEffect(() => {
    let alive = true;
    track("report_viewed", { role: "admin", period: "30d" });
    get<AdminAiQuality>("/admin/ai/quality?days=30")
      .then((r) => alive && setQ(r ?? null))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  if (!q || typeof q.answers_total !== "number") return null;
  const reasons = Object.entries(q.refusals_by_reason ?? {});
  const models = Object.entries(q.by_model ?? {});
  return (
    <section className="card">
      <h2>{t("aiqTitle")}</h2>
      <p className="muted m-0">{q.days}d</p>
      <div className="stat-grid">
        <div className="stat">
          <span className="stat-value">{q.answers_total}</span>
          <span className="stat-label">{t("aiqAnswers")}</span>
        </div>
        <div className="stat">
          <span className="stat-value">{q.grounded_count}</span>
          <span className="stat-label">{t("aiqGrounded")}</span>
        </div>
        <div className="stat">
          <span className="stat-value">{q.ungrounded_count}</span>
          <span className="stat-label">{t("aiqUngrounded")}</span>
        </div>
        <div className="stat">
          <span className="stat-value">{q.low_confidence_count}</span>
          <span className="stat-label">{t("aiqLowConf")}</span>
        </div>
      </div>
      <p className="mt-2 m-0">
        <Badge tone="ok">
          {t("aiqThumbsUp")} {q.thumbs_up}
        </Badge>{" "}
        <Badge tone={q.thumbs_down > 0 ? "warn" : "ok"}>
          {t("aiqThumbsDown")} {q.thumbs_down}
        </Badge>{" "}
        <Badge tone={q.refusals_total > 0 ? "warn" : "ok"}>
          {t("aiqRefusals")} {q.refusals_total}
        </Badge>
      </p>
      {reasons.length > 0 && (
        <p className="muted mt-2 m-0 text-sm">
          {t("aiqReasons")}:{" "}
          {reasons.map(([code, n]) => `${code} ×${n}`).join(" · ")}
        </p>
      )}
      {models.length > 0 && (
        <p className="muted mt-2 m-0 text-sm">
          {t("aiqByModel")}: {models.map(([m, n]) => `${m} ×${n}`).join(" · ")}
        </p>
      )}
    </section>
  );
}
