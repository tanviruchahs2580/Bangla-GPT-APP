import { useState } from "react";
import { forgotPassword, resetPassword, verifyEmail } from "../api";
import { Button, Field, Segmented } from "../components/ui";
import { friendlyError, type ErrorCopy } from "../errors";
import { t } from "../i18n";

type Tab = "forgot" | "verify";

export default function ForgotResetPage() {
  const [tab, setTab] = useState<Tab>("forgot");

  // The mode switch used to borrow .rate-btn (the 44x44 thumbs icon button):
  // both Bangla labels were clipped inside it and rendered in the UA font.
  // Segmented is the shared .chip toggle every other page uses.
  return (
    <main id="main-content" tabIndex={-1} className="card auth-card stack">
      <h1>{tab === "forgot" ? t("resetTitle") : t("verifyTitle")}</h1>
      <Segmented
        options={[
          { value: "forgot", label: t("resetTitle") },
          { value: "verify", label: t("verifyTitle") },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "forgot" ? <ForgotForm /> : <VerifyForm />}
      <p className="muted">
        {t("haveAccount")} <a href="/login">{t("login")}</a>
      </p>
    </main>
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
      <form onSubmit={requestToken} className="stack">
        <Field label={t("email")} htmlFor="femail">
          <input
            className="input"
            id="femail"
            type="email"
            autoComplete="email"
            value={email}
            required
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        {error && (
          <p className="error" role="alert">
            {error.text}
          </p>
        )}
        <Button variant="primary" block type="submit" disabled={busy}>
          {busy ? <span className="spinner" aria-hidden /> : t("resetTitle")}
        </Button>
      </form>
    );
  }
  return (
    <>
      <p className="ok" role="status">
        {t("forgotSent")}
      </p>
      <form onSubmit={doReset} className="stack">
        <Field label={t("locResetCode")} htmlFor="rtoken">
          <input
            className="input"
            id="rtoken"
            value={token}
            required
            minLength={16}
            onChange={(e) => setToken(e.target.value)}
          />
        </Field>
        <Field label={t("password")} htmlFor="rnewpass">
          <input
            className="input"
            id="rnewpass"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            required
            minLength={8}
            onChange={(e) => setNewPassword(e.target.value)}
          />
        </Field>
        {error && (
          <p className="error" role="alert">
            {error.text}
          </p>
        )}
        <Button variant="primary" block type="submit" disabled={busy}>
          {busy ? <span className="spinner" aria-hidden /> : t("resetTitle")}
        </Button>
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
      <form onSubmit={submit} className="stack">
        <Field label={t("locCode")} htmlFor="vcode">
          <input
            className="input"
            id="vcode"
            value={code}
            required
            minLength={16}
            onChange={(e) => setCode(e.target.value)}
          />
        </Field>
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
        <Button variant="primary" block type="submit" disabled={busy}>
          {busy ? <span className="spinner" aria-hidden /> : t("verifyBtn")}
        </Button>
      </form>
    </>
  );
}
