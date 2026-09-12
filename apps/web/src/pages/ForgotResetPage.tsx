import { useState } from "react";
import { forgotPassword, resetPassword, verifyEmail } from "../api";
import { friendlyError, type ErrorCopy } from "../errors";
import { t } from "../i18n";

type Tab = "forgot" | "verify";

export default function ForgotResetPage() {
  const [tab, setTab] = useState<Tab>("forgot");

  return (
    <div className="card auth-card">
      <h2>{tab === "forgot" ? t("resetTitle") : t("verifyTitle")}</h2>
      <p className="muted">
        <button
          className={`rate-btn${tab === "forgot" ? " on-up" : ""}`}
          onClick={() => setTab("forgot")}
        >
          {t("resetTitle")}
        </button>{" "}
        <button
          className={`rate-btn${tab === "verify" ? " on-up" : ""}`}
          onClick={() => setTab("verify")}
        >
          {t("verifyTitle")}
        </button>
      </p>
      {tab === "forgot" ? <ForgotForm /> : <VerifyForm />}
      <p className="muted">
        {t("haveAccount")} <a href="/login">{t("login")}</a>
      </p>
    </div>
  );
}

function ForgotForm() {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [requested, setRequested] = useState(false);
  const [error, setError] = useState<ErrorCopy | null>(null);
  const [busy, setBusy] = useState(false);

  async function requestToken(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await forgotPassword(email);
      setRequested(true);
    } catch (err) {
      setError(friendlyError((err as { code?: string }).code));
    } finally {
      setBusy(false);
    }
  }

  async function doReset(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, newPassword);
      window.location.href = "/student";
    } catch (err) {
      setError(friendlyError((err as { code?: string }).code));
    } finally {
      setBusy(false);
    }
  }

  if (!requested) {
    return (
      <form onSubmit={requestToken}>
        <label htmlFor="femail">{t("email")}</label>
        <input
          id="femail"
          type="email"
          autoComplete="email"
          value={email}
          required
          onChange={(e) => setEmail(e.target.value)}
        />
        {error && (
          <p className="error" role="alert">
            {error.text}
          </p>
        )}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? <span className="spinner" aria-hidden /> : t("resetTitle")}
        </button>
      </form>
    );
  }
  return (
    <>
      <p className="ok" role="status">
        {t("forgotSent")}
      </p>
      <form onSubmit={doReset}>
        <label htmlFor="rtoken">Reset code</label>
        <input
          id="rtoken"
          value={token}
          required
          minLength={16}
          onChange={(e) => setToken(e.target.value)}
        />
        <label htmlFor="rnewpass">{t("password")}</label>
        <input
          id="rnewpass"
          type="password"
          autoComplete="new-password"
          value={newPassword}
          required
          minLength={8}
          onChange={(e) => setNewPassword(e.target.value)}
        />
        {error && (
          <p className="error" role="alert">
            {error.text}
          </p>
        )}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? <span className="spinner" aria-hidden /> : t("resetTitle")}
        </button>
      </form>
    </>
  );
}

function VerifyForm() {
  const [code, setCode] = useState("");
  const [okMsg, setOkMsg] = useState<string | null>(null);
  const [error, setError] = useState<ErrorCopy | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await verifyEmail(code.trim());
      setOkMsg(t("verifiedOk"));
      setTimeout(() => {
        window.location.href = "/login";
      }, 800);
    } catch (err) {
      setError(
        friendlyError((err as { code?: string }).code ?? "invalid_token"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="muted">{t("verifySent")}</p>
      <form onSubmit={submit}>
        <label htmlFor="vcode">Code</label>
        <input
          id="vcode"
          value={code}
          required
          minLength={16}
          onChange={(e) => setCode(e.target.value)}
        />
        {okMsg && (
          <p className="ok" role="status">
            {okMsg}
          </p>
        )}
        {error && (
          <p className="error" role="alert">
            {error.text}
          </p>
        )}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? <span className="spinner" aria-hidden /> : t("verifyBtn")}
        </button>
      </form>
    </>
  );
}
