import { useQuery } from "@tanstack/react-query";
import { get } from "../../api";
import { formatNumber, t } from "../../i18n";
import { formatServerDateTime } from "../../lib/datetime";
import { LoadError } from "../ui";
import type { RefusalAudit } from "../../types";

/**
 * F-094 split: the refusal-audit card, self-contained (query included) so
 * AdminDashboard keeps only the orchestration.
 *
 * FE-FIX-005: the query function caught its own failure into `null`, which
 * made `isError` unreachable — the card showed "লোড হচ্ছে…" for the rest of the
 * session on an outage, indistinguishable from a slow load, on the governance
 * surface that exists to show what the safety screen refused. The failure is
 * no longer swallowed, so `isError` and its retry are reachable.
 */

/** Server `by_reason` codes -> copy (the lib/roles.ts rule: map server enums,
 *  never print them). Two families arrive here: the safety screen's category
 *  names (services/safety.py) and the tutor's `refused_reason` values. An
 *  unmapped code gets a named generic rather than the raw snake_case
 *  identifier (FE-FIX, raw machine copy). */
const REASON_LABEL: Record<string, Parameters<typeof t>[0]> = {
  self_harm: "admRefReasonSelfHarm",
  weapon_synthesis: "admRefReasonWeaponSynthesis",
  drug_synthesis: "admRefReasonDrugSynthesis",
  sexual_content: "admRefReasonSexualContent",
  violence: "admRefReasonViolence",
  personal_data: "admRefReasonPersonalData",
  hate_speech: "admRefReasonHateSpeech",
  bullying_harassment: "admRefReasonBullyingHarassment",
  prompt_injection: "admRefReasonPromptInjection",
  insufficient_evidence: "admRefReasonInsufficientEvidence",
  ai_busy: "admRefReasonAiBusy",
  ai_generation_disabled: "admRefReasonAiGenerationDisabled",
  model_refused: "admRefReasonModelRefused",
  output_screen: "admRefReasonOutputScreen",
  vision_unsupported: "admRefReasonVisionUnsupported",
  provider_unavailable: "admRefReasonProviderUnavailable",
  unknown: "admRefReasonUnknown",
};

function reasonLabel(code: string): string {
  const key = REASON_LABEL[code];
  return key ? t(key) : t("admRefReasonUnknown");
}

/** A map key that is a bare number is a quantity and takes the language's
 *  digits; a non-numeric key (the API can bucket under any label) is text. */
function digitsOf(value: string): string {
  return /^\d+$/.test(value) ? formatNumber(Number(value)) : value;
}

export function RefusalAuditCard() {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ["admin-refusals"],
    queryFn: () => get<RefusalAudit>("/admin/safety/refusals"),
  });
  return (
    // refusal audit -- why/where safety refusals happened (counts only).
    <div className="card">
      <h2>{t("admSafety")}</h2>
      {isPending ? (
        <p className="muted" role="status">
          {t("loading")}
        </p>
      ) : isError || !data ? (
        <LoadError onRetry={() => void refetch()} />
      ) : (
        <>
          <div className="stat-row">
            <div className="stat">
              <div className="num">{formatNumber(data.total_refusals)}</div>
              <div className="lbl">{t("admRefusals")}</div>
            </div>
          </div>
          {data.total_refusals === 0 ? (
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
                    {Object.entries(data.by_reason).map(([reason, n]) => (
                      <tr key={reason}>
                        <td>{reasonLabel(reason)}</td>
                        <td>{formatNumber(n)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted">
                {Object.entries(data.by_class).map(([cls, n]) => (
                  <span key={cls} className="mr-2">
                    {`${t("admRefusalClass")} ${digitsOf(cls)}: ${formatNumber(n)}`}
                  </span>
                ))}
              </p>
              {data.last_refusal_at && (
                <p className="muted">
                  {t("admLastRefusal")}:{" "}
                  {formatServerDateTime(data.last_refusal_at)}
                </p>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
