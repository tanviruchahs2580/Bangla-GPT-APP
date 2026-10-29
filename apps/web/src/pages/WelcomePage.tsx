import { Link } from "react-router-dom";
import {
  BookOpenCheck,
  CloudOff,
  BadgeCheck,
  ClipboardList,
  GraduationCap,
  BookOpen,
  Zap,
} from "lucide-react";
import { t } from "../i18n";
import { track } from "../lib/analytics";
import { BrandMark } from "../components/BrandMark";

/**
 * Blueprint §11 screens 01-02 (national-scale landing): brand mark,
 * headline, feature grid, stat strip and the two primary calls to action
 * (register / login). Decorative aurora is CSS-only and motion-safe.
 *
 * `splash-login` carries the same photo backdrop as the login/register
 * pages (desktop artwork + mobile portrait artwork, theme veil, low-data
 * kill switch) — one shared class, so the treatment cannot drift apart.
 */
export default function WelcomePage() {
  return (
    <main id="main-content" className="splash landing splash-login">
      <div className="splash-pattern" aria-hidden />
      <div className="landing-inner">
        <section className="landing-hero">
          <div className="splash-logo landing-logo" aria-hidden>
            <BrandMark size={96} />
          </div>
          <p className="landing-kicker">{t("landingKicker")}</p>
          <h1 className="landing-title">{t("landingHeroTitle")}</h1>
          <p className="landing-sub">{t("landingHeroSub")}</p>
          <div className="welcome-actions">
            {/* A <Button> inside a <Link> nests interactive content: two tab
                stops per call to action and a focus ring inside an anchor.
                The link carries the button's own classes instead. */}
            <Link
              to="/register"
              className="btn btn-primary btn-lg btn-block"
              onClick={() => track("welcome_cta", { cta: "register" })}
            >
              {t("welcomeStart")}
            </Link>
            <Link
              to="/login"
              className="btn btn-soft btn-lg btn-block"
              onClick={() => track("welcome_cta", { cta: "login" })}
            >
              {t("welcomeLogin")}
            </Link>
          </div>
          <ul className="trust-row" aria-label={t("locHighlights")}>
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
        </section>

        <section
          className="landing-features"
          aria-label={t("landingFeaturesLabel")}
        >
          <article className="landing-feature">
            <span className="lf-icon lf-ai" aria-hidden>
              <Zap size={20} />
            </span>
            <h2>{t("featTutorTitle")}</h2>
            <p>{t("featTutorSub")}</p>
          </article>
          <article className="landing-feature">
            <span className="lf-icon lf-warn" aria-hidden>
              <GraduationCap size={20} />
            </span>
            <h2>{t("featPracticeTitle")}</h2>
            <p>{t("featPracticeSub")}</p>
          </article>
          <article className="landing-feature">
            <span className="lf-icon lf-teal" aria-hidden>
              <BookOpen size={20} />
            </span>
            <h2>{t("featLearnTitle")}</h2>
            <p>{t("featLearnSub")}</p>
          </article>
          <article className="landing-feature">
            <span className="lf-icon" aria-hidden>
              <ClipboardList size={20} />
            </span>
            <h2>{t("featTeacherTitle")}</h2>
            <p>{t("featTeacherSub")}</p>
          </article>
        </section>

        <section className="landing-stats" aria-label={t("landingStatsLabel")}>
          <div>
            <strong>{t("statClassesValue")}</strong>
            <span>{t("statClassesLabel")}</span>
          </div>
          <div>
            <strong>{t("statRolesValue")}</strong>
            <span>{t("statRolesLabel")}</span>
          </div>
          <div>
            <strong>{t("statBanglaValue")}</strong>
            <span>{t("statBanglaLabel")}</span>
          </div>
        </section>

        <p className="muted welcome-sub">{t("welcomeTagline")}</p>
      </div>
    </main>
  );
}
