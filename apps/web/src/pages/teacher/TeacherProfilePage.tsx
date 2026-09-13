import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { useAuth } from "../../AuthContext";
import { Avatar, Badge, Button, Card } from "../../components/ui";
import { getLang, setLang, t } from "../../i18n";
import { currentTheme, toggleTheme } from "../../lib/theme";

const DEFAULT_CLASS_KEY = "bgpt_teacher_default_class";

// RENO: localized role labels (same map as MePage).
const ROLE_LABEL: Record<string, Parameters<typeof t>[0]> = {
  student: "roleStudent",
  teacher: "roleTeacher",
  parent: "roleParent",
  admin: "roleAdmin",
  school_admin: "roleSchoolAdmin",
};

/** Teacher profile: teaching defaults + the shared settings block.
 *  Default class is a client-side preference that prefills generators —
 *  there is no backend teacher-prefs endpoint yet (flagged in the report). */
export default function TeacherProfilePage() {
  const { me } = useAuth();
  const [defaultClass, setDefaultClass] = useState(() => {
    const v = localStorage.getItem(DEFAULT_CLASS_KEY);
    return v ? Number(v) || 6 : 6;
  });
  const [saved, setSaved] = useState(false);
  const [dark, setDark] = useState(currentTheme() === "dark");

  return (
    <main className="shell-main">
      <section className="section-head">
        <h1 className="page-title">{t("tpTitle")}</h1>
      </section>

      <Card>
        <div className="row-flex">
          <Avatar name={me?.name ?? me?.email ?? "?"} size="lg" />
          <div className="row-main">
            <div className="row-title profile-name">
              {me?.name ?? me?.email}
            </div>
            <div className="row-sub">{me?.email}</div>
            <div className="badge-row">
              <Badge>
                {me
                  ? ROLE_LABEL[me.role]
                    ? t(ROLE_LABEL[me.role])
                    : me.role
                  : "—"}
              </Badge>
            </div>
          </div>
        </div>
      </Card>

      <Card title={t("learningStyleTitle")}>
        <p className="muted muted-sm m-0">{t("tpPrefsHint")}</p>
        <div className="field">
          <label htmlFor="tpclass">{t("tpDefaultClass")}</label>
          <select
            id="tpclass"
            className="select"
            value={defaultClass}
            onChange={(e) => setDefaultClass(Number(e.target.value))}
          >
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        <div className="row-flex section-gap-top">
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              localStorage.setItem(DEFAULT_CLASS_KEY, String(defaultClass));
              setSaved(true);
              window.setTimeout(() => setSaved(false), 2000);
            }}
          >
            {t("save")}
          </Button>
          {saved && (
            <p className="ok m-0" role="status">
              {t("prefsSaved")}
            </p>
          )}
        </div>
      </Card>

      <Card title={t("settings")}>
        <div className="field">
          <label htmlFor="tp-lang">{t("language")}</label>
          <select
            id="tp-lang"
            className="select"
            value={getLang()}
            onChange={(e) => {
              const v = e.target.value as "bn" | "en";
              setLang(v);
              document.documentElement.setAttribute("lang", v);
              // RENO: in-place remount via LangRoot — no page reload.
            }}
          >
            <option value="bn">বাংলা</option>
            <option value="en">English</option>
          </select>
        </div>
        <div className="row-flex spread">
          <div>
            <div className="setting-label">{t("appearance")}</div>
            <div className="muted text-sm">{t("darkMode")}</div>
          </div>
          <button
            className="icon-btn"
            aria-label={t("darkMode")}
            onClick={() => setDark(toggleTheme() === "dark")}
          >
            {dark ? (
              <Sun size={18} aria-hidden />
            ) : (
              <Moon size={18} aria-hidden />
            )}
          </button>
        </div>
      </Card>
    </main>
  );
}
