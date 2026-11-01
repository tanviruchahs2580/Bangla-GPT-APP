import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import { ROLE_HOME, useAuth } from "../AuthContext";
import { t } from "../i18n";

/**
 * FE-11: unknown paths used to be redirected silently to the role home, so a
 * mistyped or stale deep link looked like the app ignoring the URL. This page
 * names the address that was not found and offers the way home.
 */
export default function NotFoundPage() {
  const { me } = useAuth();
  const home = me ? (ROLE_HOME[me.role] ?? "/") : "/welcome";
  return (
    <main id="main-content" tabIndex={-1} className="container">
      <div className="card stack center">
        <span className="empty-mark" aria-hidden>
          <Compass size={40} />
        </span>
        <h1 className="card-title">{t("noResults")}</h1>
        <p className="muted">
          {/* The exact address, so a support conversation can copy it. */}
          <code>{window.location.pathname}</code>
        </p>
        <Link className="btn btn-primary" to={home}>
          {t("brandHome")}
        </Link>
      </div>
    </main>
  );
}
