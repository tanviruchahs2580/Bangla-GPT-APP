import { useState } from "react";
import { applyTelemetryConsent, telemetryConsent } from "../lib/telemetry";
import { t } from "../i18n";

/**
 * Consent-gated client telemetry switch (AUD-HI-07 / I-12).
 *
 * Default OFF: the initial state comes from `telemetryConsent()`, which treats
 * an unset flag, blocked storage and a parse failure all as "no". Flipping it
 * calls `applyTelemetryConsent`, which starts or closes the Sentry client.
 *
 * One component, two pages (student profile + teacher profile): the two copies
 * this replaced were byte-identical, which is how a consent toggle ends up
 * behaving differently per role after one of them is edited.
 */
export function TelemetryToggle() {
  const [on, setOn] = useState(telemetryConsent);
  return (
    <div className="row-flex spread mt-3">
      <div>
        <div className="setting-label">{t("telemetryTitle")}</div>
        <div className="muted text-sm">{t("telemetryHint")}</div>
      </div>
      <button
        className="switch"
        role="switch"
        aria-checked={on}
        aria-label={t("telemetryTitle")}
        onClick={() => {
          const next = !on;
          applyTelemetryConsent(next);
          setOn(next);
        }}
      />
    </div>
  );
}

export default TelemetryToggle;
