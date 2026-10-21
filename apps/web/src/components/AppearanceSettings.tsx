import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { getLang, setLang, t } from "../i18n";
import { currentTheme, toggleTheme } from "../lib/theme";

/**
 * The language + appearance block of the settings card.
 *
 * Extracted from the student and teacher profile pages, whose copies were
 * identical: two copies of a settings block is how one role keeps a
 * fixed-in-one-place bug (the audit's duplication ratchet caught exactly
 * that). The `idPrefix` keeps the `<label for>` unique when both could ever
 * render on one page.
 */
export function AppearanceSettings({ idPrefix }: { idPrefix: string }) {
  const [lang, setLangState] = useState(getLang());
  const [theme, setTheme] = useState(currentTheme());
  const selectId = `${idPrefix}-lang`;

  return (
    <>
      <div className="field">
        <label htmlFor={selectId}>{t("language")}</label>
        <select
          id={selectId}
          className="select"
          value={lang}
          onChange={(e) => {
            const next = e.target.value as "bn" | "en";
            setLang(next);
            setLangState(next);
            document.documentElement.setAttribute("lang", next);
            // LangRoot remounts the tree in place — no page reload.
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
          onClick={() => setTheme(toggleTheme())}
        >
          {theme === "dark" ? (
            <Sun size={18} aria-hidden />
          ) : (
            <Moon size={18} aria-hidden />
          )}
        </button>
      </div>
    </>
  );
}

export default AppearanceSettings;
