import { useState } from "react";
import { login, register, resendVerification, verifyEmail } from "../api";
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
  // In an SMTP-enabled deployment the account exists but is unusable until the
  // mailed code is redeemed. The screen used to say "enter the code we emailed
  // you" with no field and no link -- the only code entry lived on the
  // forgot-password page -- so a new user could not finish signing up at all.
  const [verifyPending, setVerifyPending] = useState(false);
  const [vcode, setVcode] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (role === "student" && !consent) {
      setError({ text: t("consentRequired") });
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
        setMe((await login(email, password)).me);
      } catch (verifyErr) {
        const code = (verifyErr as { code?: string }).code;
        if (code === "email_unverified") {
          setVerifyPending(true);
          setNotice(t("verifySent"));
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

  async function submitVerify(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await verifyEmail(vcode.trim());
      setNotice(null);
      // verification issues a session, but signing in again keeps this flow
      // identical to the plain login path (and refreshes the profile).
      setMe((await login(email, password)).me);
    } catch (err) {
      setError(
        friendlyError((err as { code?: string }).code ?? "invalid_token"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    try {
      await resendVerification(email);
      setNotice(t("verifySent"));
    } catch (err) {
      setError(friendlyError((err as { code?: string }).code));
    }
  }

  return (
    // Shares login's photo backdrop (.splash-login): the desktop artwork, the
    // portrait mobile artwork with its ambient fill, the dark-mode veil and
    // the low-data kill-switch all live in that one class.
    <main id="main-content" className="splash splash-login auth-shell">
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
        <h2>{verifyPending ? t("verifyTitle") : t("register")}</h2>
        {verifyPending ? (
          <>
            {notice && (
              <p className="muted" role="status">
                {notice}
              </p>
            )}
            <form onSubmit={submitVerify}>
              <div className="field">
                <label htmlFor="vcode">{t("verifyTitle")}</label>
                <input
                  className="input"
                  id="vcode"
                  value={vcode}
                  required
                  minLength={16}
                  autoComplete="one-time-code"
                  onChange={(e) => setVcode(e.target.value)}
                />
              </div>
              {error && (
                <p className="error" role="alert">
                  {error.text}
                </p>
              )}
              <Button variant="primary" block type="submit" disabled={busy}>
                {t("verifyBtn")}
              </Button>
            </form>
            <div className="link-row link-row-center">
              <Button variant="ghost" size="sm" type="button" onClick={resend}>
                {t("resendVerification")}
              </Button>
            </div>
            <div className="link-row link-row-center">
              <a href="/login">{t("login")}</a>
            </div>
          </>
        ) : (
          <>
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
                        {t("consentPrefix")}{" "}
                        <a href="/privacy" target="_blank" rel="noreferrer">
                          {t("privacy")}
                        </a>{" "}
                        ·{" "}
                        <a href="/terms" target="_blank" rel="noreferrer">
                          {t("terms")}
                        </a>{" "}
                        {t("consentSuffix")}
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
          </>
        )}
      </Card>
    </main>
  );
}
