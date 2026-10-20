/**
 * Quiz confetti — CSS/JS ≤2KB, self-cleaning, reduced-motion safe.
 * Call once on good scores; no-ops under prefers-reduced-motion.
 */
/*
 * G-01: the palette resolves the design tokens at runtime (getComputedStyle on
 * the theme element) instead of carrying hex values here, so a theme change
 * re-themes the celebration too.
 *
 * The previous version named three variables that do not exist in the token
 * layer (`--info`, `--indigo`, `--warning`), so `getPropertyValue` returned ""
 * for them and the literal fallbacks were what actually painted -- the palette
 * was frozen even though it looked token-driven. The names below are the ones
 * `styles.css` declares, and there are no literals left to fall back to: a
 * token that cannot be resolved is skipped rather than replaced by a colour
 * that no theme owns.
 */
const COLOR_VARS = [
  "--brand-600",
  "--brand-500",
  "--teal",
  "--ai",
  "--amber",
  "--pink",
] as const;

function palette(): string[] {
  try {
    const styles = getComputedStyle(document.documentElement);
    return COLOR_VARS.map((name) =>
      styles.getPropertyValue(name).trim(),
    ).filter(Boolean);
  } catch {
    return [];
  }
}

export function celebrate(scorePct: number): void {
  try {
    if (scorePct < 70) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const colors = palette();
    // No stylesheet (a pre-CSS frame, a non-browser test runner): there is no
    // colour to paint with, so there is nothing to celebrate.
    if (colors.length === 0) return;
    const n = scorePct >= 90 ? 28 : 16;
    for (let i = 0; i < n; i++) {
      const s = document.createElement("span");
      s.className = "confetti-piece";
      s.style.left = `${4 + Math.random() * 92}vw`;
      s.style.background = colors[i % colors.length];
      s.style.animationDelay = `${Math.random() * 0.35}s`;
      s.style.transform = `rotate(${Math.random() * 180}deg)`;
      document.body.appendChild(s);
      window.setTimeout(() => s.remove(), 2200);
    }
    window.setTimeout(() => {
      document.querySelectorAll(".confetti-piece").forEach((el) => el.remove());
    }, 2600);
  } catch {
    /* celebration must never break results */
  }
}
