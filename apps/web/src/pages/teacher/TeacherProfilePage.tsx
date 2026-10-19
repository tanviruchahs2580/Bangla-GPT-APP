import { useState } from "react";
import { useAuth } from "../../AuthContext";
import { Avatar, Badge, Button, Card } from "../../components/ui";
import { ClassLevelSelect } from "../../components/ClassLevelSelect";
import { TelemetryToggle } from "../../components/TelemetryToggle";
import { AppearanceSettings } from "../../components/AppearanceSettings";
import { t } from "../../i18n";
import { roleLabel } from "../../lib/roles";

const DEFAULT_CLASS_KEY = "bgpt_teacher_default_class";

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

  return (
    <main id="main-content" tabIndex={-1} className="shell-main">
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
              <Badge>{me ? roleLabel(me.role) : "—"}</Badge>
            </div>
          </div>
        </div>
      </Card>

      <Card title={t("learningStyleTitle")}>
        <p className="muted muted-sm m-0">{t("tpPrefsHint")}</p>
        <div className="field">
          <label htmlFor="tpclass">{t("tpDefaultClass")}</label>
          <ClassLevelSelect
            id="tpclass"
            value={defaultClass}
            onChange={setDefaultClass}
          />
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
        <AppearanceSettings idPrefix="tp" />
        <TelemetryToggle />
      </Card>
    </main>
  );
}
