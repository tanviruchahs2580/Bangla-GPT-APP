import { Languages } from "lucide-react";
import { getLang, setLang, t } from "../i18n";

/**
 * Language switch for the pages an anonymous visitor sees.
 *
 * The shell's toggle lives in AppShell, which wraps only the signed-in routes.
 * Before this existed a visitor could not read the welcome, login, register,
 * status or legal pages in the other language at all: the copy follows a
 * stored preference they had no way to set until after signing in. I18N-12
 * requires the toggle to be available and to apply immediately, so this uses
 * the same button, icon and mechanism as AppShell deliberately -- two controls
 * that behaved differently would be worse than one.
 */
export function PublicLanguageToggle() {
  return (
    <button
      type="button"
      className="icon-btn public-lang-toggle"
      aria-label={t("language")}
      onClick={() => {
        const next = getLang() === "bn" ? "en" : "bn";
        setLang(next);
        document.documentElement.setAttribute("lang", next);
      }}
    >
      <Languages size={18} aria-hidden />
    </button>
  );
}
