import { Link } from "react-router-dom";
import { BookOpenCheck, CloudOff, BadgeCheck } from "lucide-react";
import { t } from "../i18n";
import { track } from "../lib/analytics";
import { Button } from "../components/ui";
import { BrandMark } from "../components/BrandMark";

/**
 * Blueprint §11 screens 01-02: splash + welcome. Public entry shown before
 * authentication: brand mark, product name, tagline, and the two primary
 * calls to action (register / login). No animation-heavy intro by design.
 */
export default function WelcomePage() {
  return (
    <main className="splash welcome-screen">
      <div className="splash-pattern" aria-hidden />
      <div className="splash-logo" aria-hidden>
        <BrandMark size={84} />
      </div>
      <h1>{t("appName")}</h1>
      <p className="welcome-tagline">{t("welcomeTagline")}</p>
      <div className="welcome-actions">
        <Link
          to="/register"
          onClick={() => track("welcome_cta", { cta: "register" })}
        >
          <Button variant="primary" size="lg" block>
            {t("welcomeStart")}
          </Button>
        </Link>
        <Link
          to="/login"
          onClick={() => track("welcome_cta", { cta: "login" })}
        >
          <Button variant="soft" size="lg" block>
            {t("welcomeLogin")}
          </Button>
        </Link>
      </div>
      <p className="muted welcome-sub">{t("welcomeSub")}</p>
      <ul className="trust-row" aria-label="highlights">
        <li>
          <BadgeCheck size={16} aria-hidden />
          <span>{t("trustNctb")}</span>
        </li>
        <li>
          <BookOpenCheck size={16} aria-hidden />
          <span>{t("trustAi")}</span>
        </li>
        <li>
          <CloudOff size={16} aria-hidden />
          <span>{t("trustOffline")}</span>
        </li>
      </ul>
    </main>
  );
}
