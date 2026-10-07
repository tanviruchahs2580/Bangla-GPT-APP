import { useState } from "react";
import { changePassword, login, mfaChallenge } from "../api";
import { useAuth } from "../AuthContext";
import { friendlyError, type ErrorCopy } from "../errors";
import { t } from "../i18n";
import { Button, Card } from "../components/ui";
import { BrandMark } from "../components/BrandMark";
import { BadgeCheck, BookOpenCheck, CloudOff } from "lucide-react";

export default function LoginPage() {
  const { setMe } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ErrorCopy | null>(null);
  const [busy, setBusy] = useState(false);
  // MFA step-up: login answers 202 mfa_required with a purpose-bound token
  // (NOT a session). The OTP form exchanges it for a real session; the
  // step-up token is never stored as one.
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  // Server flags a mandatory password change (provisioned accounts, temp
  // secrets). The API 403s every non-exempt route until it is done, so the
  // change form blocks the session here instead of the dashboard failing.
  const [pendingMe, setPendingMe] = useState<
    Awaited<ReturnType<typeof login>>["me"] | null
  >(null);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      // login() verifies the session and returns the server profile —
      // seeding auth state from it avoids a second /users/me round-trip.
      const { me, mustChangePassword } = await login(email, password);
      if (mustChangePassword) {
        setPendingMe(me);
      } else {
        setMe(me);
      }
    } catch (err) {
      const apiErr = err as {
        code?: unknown;
        message?: string;
        rawDetail?: unknown;
      };
      const code = typeof apiErr.code === "string" ? apiErr.code : undefined;
      // Second factor required: hold the step-up token and show the OTP
      // form instead of an error dead-end.
      if (code === "mfa_required") {
        const detail = apiErr.rawDetail as
          | { mfa_token?: string; mfaToken?: string }
          | undefined;
        const stepUp =
          detail && typeof detail === "object"
            ? (detail.mfa_token ?? detail.mfaToken)
            : undefined;
        if (typeof stepUp === "string" && stepUp) {
          setMfaToken(stepUp);
          setMfaCode("");
          setError(null);
          return;
        }
      }
      setError(
        friendlyError({
          code,
          message: apiErr.message,
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitMfa(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !mfaToken) return;
    setBusy(true);
    setError(null);
    try {
      const { me, mustChangePassword } = await mfaChallenge(
        mfaToken,
        mfaCode.trim(),
      );
      setMfaToken(null);
      if (mustChangePassword) {
        setPendingMe(me);
      } else {
        setMe(me);
      }
    } catch (err) {
      const apiErr = err as { code?: unknown; message?: string };
      const code = typeof apiErr.code === "string" ? apiErr.code : undefined;
      // An expired step-up token cannot be retried — drop back to login.
      if (code === "bad_mfa_token") setMfaToken(null);
      setError(
        friendlyError({
          code,
          message: apiErr.message,
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitPasswordChange(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (newPassword !== confirmPassword) {
      setError({ text: t("passwordMismatch") });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await changePassword(password, newPassword);
      setMe(pendingMe);
    } catch (err) {
      const apiErr = err as { code?: unknown; message?: string };
      setError(
        friendlyError({
          code: typeof apiErr.code === "string" ? apiErr.code : undefined,
          message: apiErr.message,
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  if (mfaToken) {
    return (
      <div className="splash splash-login auth-shell">
        <Card className="auth-card">
          <h2>{t("mfaTitle")}</h2>
          <p className="muted">{t("mfaHint")}</p>
          <form onSubmit={submitMfa}>
            <div className="field">
              <label htmlFor="mfa-code">{t("mfaCode")}</label>
              <input
                className="input"
                id="mfa-code"
                name="one-time-code"
                autoComplete="one-time-code"
                inputMode="numeric"
                type="text"
                value={mfaCode}
                required
                minLength={6}
                maxLength={6}
                pattern="[0-9]{6}"
                onChange={(e) => setMfaCode(e.target.value)}
              />
            </div>
            {error && (
              <p className="error" role="alert">
                {error.text}
              </p>
            )}
            <Button variant="primary" block type="submit" disabled={busy}>
              {t("mfaSubmit")}
            </Button>
          </form>
        </Card>
      </div>
    );
  }

  if (pendingMe) {
    return (
      <div className="splash splash-login auth-shell">
        <Card className="auth-card">
          <h2>{t("forceChangeTitle")}</h2>
          <p className="muted">{t("forceChangeSub")}</p>
          <form onSubmit={submitPasswordChange}>
            <div className="field">
              <label htmlFor="current-password">{t("currentPassword")}</label>
              <input
                className="input"
                id="current-password"
                name="current-password"
                autoComplete="current-password"
                type="password"
                value={password}
                required
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="new-password">{t("newPassword")}</label>
              <input
                className="input"
                id="new-password"
                name="new-password"
                autoComplete="new-password"
                type="password"
                value={newPassword}
                required
                minLength={8}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="confirm-password">{t("confirmPassword")}</label>
              <input
                className="input"
                id="confirm-password"
                name="confirm-password"
                autoComplete="new-password"
                type="password"
                value={confirmPassword}
                required
                minLength={8}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>
            {error && (
              <p className="error" role="alert">
                {error.text}
              </p>
            )}
            <Button variant="primary" block type="submit" disabled={busy}>
              {t("forceChangeSubmit")}
            </Button>
          </form>
        </Card>
      </div>
    );
  }

  return (
    <div className="splash splash-login auth-shell">
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
        <h2>{t("login")}</h2>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="email">{t("email")}</label>
            <input
              className="input"
              id="email"
              name="email"
              autoComplete="email"
              type="email"
              value={email}
              required
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">{t("password")}</label>
            <input
              className="input"
              id="password"
              name="password"
              autoComplete="current-password"
              type="password"
              value={password}
              required
              minLength={8}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && (
            <p className="error" role="alert">
              {error.text}
              {error.action === "resend-verification" && (
                <>
                  {" "}
                  <a
                    href="/forgot"
                    onClick={(e) => {
                      e.preventDefault();
                      const typedEmail = email.trim() || undefined;
                      void import("../api").then(({ resendVerification }) =>
                        resendVerification(typedEmail).then(
                          () => setError({ text: t("verifySent") }),
                          () => setError({ text: t("errGeneric") }),
                        ),
                      );
                    }}
                  >
                    {t("resendVerification")}
                  </a>
                </>
              )}
            </p>
          )}
          <Button variant="primary" block type="submit" disabled={busy}>
            {t("login")}
          </Button>
        </form>
        <div className="link-row">
          <a href="/forgot">{t("forgot")}</a>
          <a href="/register">{t("register")}</a>
        </div>
      </Card>
    </div>
  );
}
