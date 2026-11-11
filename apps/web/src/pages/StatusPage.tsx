import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, AlertTriangle, RefreshCw } from "lucide-react";
import { getStatus } from "../api";
import { friendlyError } from "../errors";
import { t } from "../i18n";
import { formatServerDateTime } from "../lib/datetime";
import type { StatusOut } from "../types";

/**
 * public status page. The payload is presence/booleans only by design
 * : the endpoint never exposes usage counts or configuration.
 *
 * FE-FIX-017: the API answers with English machine strings
 * (routers/system.py: `name="cache"`, `detail="shared cache reachable"`,
 * `"no LLM provider configured"`), and this page printed them verbatim — the
 * only English left in the product, on the page linked from every footer. The
 * server contract is unchanged: the client maps it, exactly as `lib/roles.ts`
 * maps role enums. A detail with no copy here is named generically rather than
 * leaked, and the component's own ok/degraded mark still carries the verdict.
 */
const COMPONENT_LABEL: Record<string, Parameters<typeof t>[0]> = {
  database: "statusCompDatabase",
  cache: "statusCompCache",
  assistant: "statusCompAssistant",
  curriculum: "statusCompCurriculum",
};

const DETAIL_LABEL: Record<string, Parameters<typeof t>[0]> = {
  "queries responding": "statusDetailQueriesOk",
  unreachable: "statusDetailUnreachable",
  "shared cache reachable": "statusDetailCacheShared",
  "in-process cache active": "statusDetailCacheLocal",
  "cache unreachable": "statusDetailCacheDown",
  "no LLM provider configured": "statusDetailNoProvider",
  "provider circuit open after repeated failures": "statusDetailCircuitOpen",
  "last provider call succeeded": "statusDetailProviderOk",
  "provider configured": "statusDetailProviderSet",
  "retrieval index loaded": "statusDetailIndexOk",
  "retrieval index unavailable": "statusDetailIndexDown",
};

function componentLabel(name: string): string {
  const key = COMPONENT_LABEL[name];
  return key ? t(key) : t("statusCompUnknown");
}

/** The provider lane sends a counted sentence built at runtime
 *  (`"{n} consecutive provider calls failed"`), so it is matched, not looked
 *  up — the count is interpolated and therefore renders in Bangla digits. */
const PROVIDER_FAILURES = /^(\d+) consecutive provider calls failed$/;

function detailLabel(detail: string): string {
  const key = DETAIL_LABEL[detail];
  if (key) return t(key);
  const counted = PROVIDER_FAILURES.exec(detail);
  if (counted)
    return t("statusDetailProviderFailed", { n: Number(counted[1]) });
  return t("statusDetailUnknown");
}

export default function StatusPage() {
  const [data, setData] = useState<StatusOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    getStatus()
      .then((res) => {
        if (live) {
          setData(res);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (live)
          setError(
            friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
              t("errorGeneric"),
          );
      });
    return () => {
      live = false;
    };
  }, [tick]);

  const ok = data?.status === "ok";

  return (
    <main id="main-content" tabIndex={-1} className="card card-narrow">
      <h1>{t("statusPage")}</h1>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {data === null && !error && <p className="muted">{t("loading")}</p>}
      {data && (
        <>
          <div
            role="status"
            className={ok ? "status-hero" : "status-hero degraded"}
          >
            {ok ? (
              <CheckCircle2 size={20} aria-hidden />
            ) : (
              <AlertTriangle size={20} aria-hidden />
            )}
            {ok ? t("statusAllOk") : t("statusDegraded")}
          </div>
          <ul className="status-list">
            {data.components.map((c) => (
              <li key={c.name} className="status-item">
                {c.ok ? (
                  <CheckCircle2 size={16} aria-hidden className="status-ok" />
                ) : (
                  <AlertTriangle
                    size={16}
                    aria-hidden
                    className="status-warn"
                  />
                )}
                <strong>{componentLabel(c.name)}</strong>
                <span className="muted">{detailLabel(c.detail)}</span>
              </li>
            ))}
          </ul>
          <p className="muted">
            {t("statusChecked", {
              when: formatServerDateTime(data.checked_at),
            })}{" "}
            <button
              className="small secondary"
              onClick={() => setTick((n) => n + 1)}
              aria-label={t("refreshBtn")}
            >
              <RefreshCw size={12} aria-hidden />
            </button>
          </p>
        </>
      )}
      <p>
        <Link to="/login">{t("login")}</Link>
      </p>
    </main>
  );
}
