import { useState } from "react";
import { fetchMe, login, register } from "../api";
import { useAuth } from "../AuthContext";
import { friendlyError, type ErrorCopy } from "../errors";
import { t } from "../i18n";
import { Button, Card } from "../components/ui";
import { BrandMark } from "../components/BrandMark";
import { BadgeCheck, BookOpenCheck, CloudOff } from "lucide-react";

export default function RegisterPage() {
  const { setMe } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"student" | "teacher" | "parent">("student");
  const [classLevel, setClassLevel] = useState(6);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<ErrorCopy | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (role === "student" && !consent) {
      setError({ text: t("consentText") });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await register({
        email,
        password,
        name,
        role,
        class_level: role === "student" ? classLevel : undefined,
        guardian_consent: role === "student",
      });
      // SMTP-verified deployments land on the verify screen; others go straight in.
      try {
        await login(email, password);
        setMe(await fetchMe());
      } catch (verifyErr) {
        const code = (verifyErr as { code?: string }).code;
        if (code === "email_unverified") {
          setError({ text: t("verifySent"), action: undefined });
        } else {
          throw verifyErr;
        }
      }
    } catch (err) {
      setError(friendlyError((err as { code?: string }).code));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="splash auth-shell">
      <section className="auth-brand">
        <div className="auth-brand-head">
          <span className="auth-brand-logo" aria-hidden>
            <BrandMark size={64} />
          </span>
          <div>
            <p className="auth-brand-kicker">{t("landingKicker")}</p>
            <h1 className="auth-brand-title">{t("appName")}</h1>
            <p className="auth-brand-sub">{t("welcomeTagline")}</p>
          </div>
        </div>
        <ul className="auth-brand-list">
          <li>
            <BadgeCheck size={18} aria-hidden />
            <span>{t("trustNctb")}</span>
          </li>
          <li>
            <BookOpenCheck size={18} aria-hidden />
            <span>{t("trustAi")}</span>
          </li>
          <li>
            <CloudOff size={18} aria-hidden />
            <span>{t("trustOffline")}</span>
          </li>
        </ul>
        <p className="auth-brand-note muted">{t("authBrandNote")}</p>
      </section>
      <Card className="auth-card">
        <h2>{t("register")}</h2>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="role">{t("role")}</label>
            <select
              className="select"
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value as typeof role)}
            >
              <option value="student">{t("roleStudent")}</option>
              <option value="teacher">{t("roleTeacher")}</option>
              <option value="parent">{t("roleParent")}</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="name">{t("name")}</label>
            <input
              className="input"
              id="name"
              autoComplete="name"
              value={name}
              required
              minLength={2}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="remail">{t("email")}</label>
            <input
              className="input"
              id="remail"
              type="email"
              autoComplete="email"
              value={email}
              required
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="rpassword">{t("password")}</label>
            <input
              className="input"
              id="rpassword"
              name="new-password"
              autoComplete="new-password"
              type="password"
              value={password}
              required
              minLength={8}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {role === "student" && (
            <>
              <div className="field">
                <label htmlFor="class">{t("className")}</label>
                <input
                  className="input"
                  id="class"
                  type="number"
                  min={1}
                  max={12}
                  value={classLevel}
                  onChange={(e) => setClassLevel(Number(e.target.value))}
                />
              </div>
              <div className="field">
                <label htmlFor="consent" className="consent-label">
                  <input
                    id="consent"
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                    required
                    className="consent-check"
                  />
                  <span>
                    {t("consentText").replace("গোপনীয়তা নীতি ও শর্তাবলি", "")}{" "}
                    <a href="/privacy" target="_blank" rel="noreferrer">
                      {t("privacy")}
                    </a>{" "}
                    ·{" "}
                    <a href="/terms" target="_blank" rel="noreferrer">
                      {t("terms")}
                    </a>
                  </span>
                </label>
              </div>
            </>
          )}
          {error && (
            <p className="error" role="alert">
              {error.text}
              {error.action === "resend-verification" && (
                <>
                  {" "}
                  <a href="/forgot">{t("verifyTitle")}</a>
                </>
              )}
            </p>
          )}
          <Button variant="primary" block type="submit" disabled={busy}>
            {t("register")}
          </Button>
        </form>
        <div className="link-row link-row-center">
          <a href="/login">
            {t("haveAccount")} {t("login")}
          </a>
        </div>
      </Card>
    </div>
  );
}
