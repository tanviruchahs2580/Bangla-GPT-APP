import { useState } from "react";
import { fetchMe, login } from "../api";
import { useAuth } from "../AuthContext";
import { friendlyError, type ErrorCopy } from "../errors";
import { t } from "../i18n";
import { Button, Card } from "../components/ui";

export default function LoginPage() {
  const { setMe } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ErrorCopy | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      setMe(await fetchMe());
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

  return (
    <div className="splash">
      <div className="splash-logo" aria-hidden>
        🎓
      </div>
      <h1>{t("appName")}</h1>
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
                      void import("../api").then(({ resendVerification }) =>
                        resendVerification().then(() =>
                          setError({ text: t("verifySent") }),
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
