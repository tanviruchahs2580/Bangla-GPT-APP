import { t } from "../i18n";

/**
 * WCAG 2.4.1 (A11Y-01/A11Y-02). The first focusable element of every route.
 *
 * Without it a keyboard user tabs through the repeated topbar (up to eight
 * controls) plus the staff sidebar again and again before reaching the page,
 * and a screen reader user gets no direct way past the chrome. It targets the
 * route's `<main id="main-content" tabIndex={-1}>`; the link stays visually hidden until it
 * is focused (see `.skip-link` in styles.css).
 */
export function SkipLink() {
  return (
    <a className="skip-link" href="#main-content">
      {t("skipToContent")}
    </a>
  );
}
