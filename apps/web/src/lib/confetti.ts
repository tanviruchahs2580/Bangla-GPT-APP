/**
 * Quiz confetti — CSS/JS ≤2KB, self-cleaning, reduced-motion safe.
 * Call once on good scores; no-ops under prefers-reduced-motion.
 */
/*
 * G-01: the palette reads the design tokens at runtime (getComputedStyle on
 * the theme element) instead of duplicating hex values here — a theme change
 * re-themeing the celebration was previously impossible. The fallbacks are the
 * same hex values, preserved so a pre-CSS frame still celebrates in colour.
 */
const COLOR_VARS = [
  ["--brand-600", "#16a34a"],
  ["--brand-500", "#4ade80"],
  ["--info", "#0284c7"],
  ["--indigo", "#4f46e5"],
  ["--warning", "#f59e0b"],
  ["--pink", "#f472b6"],
] as const;

function palette(): string[] {
  try {
    const styles = getComputedStyle(document.documentElement);
    const resolved = COLOR_VARS.map(([name, fallback]) => {
      const value = styles.getPropertyValue(name).trim();
      return value || fallback;
    });
    return resolved.some(Boolean) ? resolved : COLOR_VARS.map(([, fb]) => fb);
  } catch {
    return COLOR_VARS.map(([, fb]) => fb);
  }
}

export function celebrate(scorePct: number): void {
  try {
    if (scorePct < 70) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const n = scorePct >= 90 ? 28 : 16;
    for (let i = 0; i < n; i++) {
      const s = document.createElement("span");
      s.className = "confetti-piece";
      s.style.left = `${4 + Math.random() * 92}vw`;
      s.style.background = palette()[i % 6];
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
