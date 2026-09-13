import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, AlertTriangle, RefreshCw } from "lucide-react";
import { getStatus } from "../api";
import { friendlyError } from "../errors";
import { t } from "../i18n";
import type { StatusOut } from "../types";

/**
 * S5.10 public status page. The payload is presence/booleans only by design
 * (R11): the endpoint never exposes usage counts or configuration.
 */
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
    <div className="card card-narrow">
      <h2>{t("statusPage")}</h2>
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
                <strong>{c.name}</strong>
                <span className="muted">{c.detail}</span>
              </li>
            ))}
          </ul>
          <p className="muted">
            {t("statusChecked", {
              when: new Date(data.checked_at).toLocaleString(),
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
    </div>
  );
}
