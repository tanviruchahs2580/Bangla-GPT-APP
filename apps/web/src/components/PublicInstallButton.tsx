import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { t } from "../i18n";
import {
  canInstall,
  onInstallChange,
  promptInstall,
} from "../lib/installPrompt";

/**
 * Install affordance for the pages an anonymous visitor sees.
 *
 * WHY THIS EXISTS. `installPrompt.ts` calls `preventDefault()` on
 * `beforeinstallprompt` so the app can own the install flow and call `prompt()`
 * when the user taps its own button. Deferring the event like that also
 * suppresses Chromium's native install UI — menu item and mini-infobar alike.
 *
 * The app's replacement affordance lived only in `AppShell`'s top bar, and
 * `AppShell` wraps only the signed-in routes. So a visitor on `/login`,
 * `/welcome`, `/register`, `/forgot`, `/status`, `/privacy` or `/terms` had
 * **no way to install at all**: the browser's prompt had been deferred and the
 * app's button did not exist yet. Installing the PWA therefore required
 * creating an account first, which is backwards — the install prompt is
 * supposed to be what brings a student back.
 *
 * Same button, icon, mechanism and vocabulary as `AppShell` deliberately; two
 * install controls that behaved differently would be worse than one. This
 * mirrors `PublicLanguageToggle`, which exists for the same reason: the shell's
 * language switch is unreachable before signing in.
 */
export function PublicInstallButton() {
  const [installable, setInstallable] = useState(canInstall());

  // Re-render when the browser offers the event, or after an install.
  useEffect(() => onInstallChange(() => setInstallable(canInstall())), []);

  // Nothing to offer once installed, or while the browser has not offered it.
  if (!installable) return null;

  return (
    <button
      type="button"
      className="icon-btn public-install-btn"
      aria-label={t("installApp")}
      onClick={() => void promptInstall()}
    >
      <Download size={18} aria-hidden />
    </button>
  );
}
