import { t } from "../i18n";

/**
 * The id every route's primary `<main>` landmark carries, so the bypass link
 * below has one stable target. Pages render their own `<main>`, so the
 * attribute lives on the pages rather than being injected here.
 */
export const MAIN_CONTENT_ID = "main-content";

/**
 * Bypass-blocks link (WCAG 2.4.1).
 *
 * Rendered once, above the shell and above the public routes, so it is the
 * first focusable element in DOM order on every screen. It is off-screen until
 * focused, then pinned to the top-left corner. The target `<main>` carries
 * `tabIndex={-1}` so focus actually moves there instead of only scrolling.
 */
export function SkipLink() {
  return (
    <a className="skip-link" href={`#${MAIN_CONTENT_ID}`}>
      {t("skipToContent")}
    </a>
  );
}
