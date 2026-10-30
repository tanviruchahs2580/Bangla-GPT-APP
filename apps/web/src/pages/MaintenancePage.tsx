import { Link } from "react-router-dom";
import { RefreshCw, Wrench } from "lucide-react";
import { t } from "../i18n";

/**
 * UX-06: the planned-maintenance screen. Before this, a maintenance window
 * could only surface as per-request error copy on whatever page the user was
 * on. The deployment points `/maintenance` at this route (nginx/vercel
 * rewrite) while a window is open; the copy is the same honest pair the API
 * outage screen uses — the account is fine, nothing was lost — because that
 * is exactly true during maintenance.
 */
export default function MaintenancePage() {
  return (
    <main id="main-content" tabIndex={-1} className="container">
      <div className="card stack center">
        <span className="empty-mark" aria-hidden>
          <Wrench size={40} />
        </span>
        <h1 className="card-title">{t("apiUnreachableTitle")}</h1>
        <p className="muted">{t("apiUnreachableBody")}</p>
        <div className="row-flex">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => window.location.reload()}
          >
            <RefreshCw size={16} aria-hidden /> {t("retry")}
          </button>
          <Link className="btn btn-ghost" to="/status">
            {t("statusPage")}
          </Link>
        </div>
      </div>
    </main>
  );
}
