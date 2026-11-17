export type Theme = "light" | "dark";

const THEME_KEY = "bgpt_theme";

const themeListeners = new Set<() => void>();

export function onThemeChange(fn: () => void): () => void {
  themeListeners.add(fn);
  return () => themeListeners.delete(fn);
}

function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_KEY, theme);
  syncThemeColorMeta(theme);
  for (const fn of themeListeners) fn();
}

export function toggleTheme(): Theme {
  const next: Theme =
    document.documentElement.getAttribute("data-theme") === "dark"
      ? "light"
      : "dark";
  applyTheme(next);
  return next;
}

export function currentTheme(): Theme {
  return document.documentElement.getAttribute("data-theme") === "dark"
    ? "dark"
    : "light";
}

// M1: the static theme-color metas in index.html only follow the OS
// preference, so a manual toggle left the browser UI in the opposite
// colour. Both metas are set to the active colour on every apply — the
// media-query meta then agrees whatever the OS setting is.
const THEME_META_COLORS: Record<Theme, string> = {
  light: "#166534",
  dark: "#12140e",
};

function syncThemeColorMeta(theme: Theme): void {
  const color = THEME_META_COLORS[theme];
  for (const meta of document.querySelectorAll<HTMLMetaElement>(
    'meta[name="theme-color"]',
  )) {
    meta.setAttribute("content", color);
  }
}
