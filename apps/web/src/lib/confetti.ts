/**
 * Quiz confetti (WP-09) — CSS/JS ≤2KB, self-cleaning, reduced-motion safe.
 * Call once on good scores; no-ops under prefers-reduced-motion.
 */
const COLORS = [
  "#16a34a",
  "#4ade80",
  "#0284c7",
  "#4f46e5",
  "#f59e0b",
  "#f472b6",
];

export function celebrate(scorePct: number): void {
  try {
    if (scorePct < 70) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const n = scorePct >= 90 ? 28 : 16;
    for (let i = 0; i < n; i++) {
      const s = document.createElement("span");
      s.className = "confetti-piece";
      s.style.left = `${4 + Math.random() * 92}vw`;
      s.style.background = COLORS[i % COLORS.length];
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
