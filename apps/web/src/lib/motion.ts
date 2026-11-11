/**
 * Reduced-motion query, in one place.
 *
 * FE-FIX-014: the tutor viewport force-scrolled with `behavior: "smooth"` on
 * every 80 ms stream flush. `lib/confetti.ts` already honoured
 * `prefers-reduced-motion`; the autoscroll, which is far more disruptive for a
 * motion-sensitive reader (the whole transcript slides under them, repeatedly),
 * did not. Guarded for environments without `matchMedia` (jsdom, older
 * WebViews) — the safe default there is "no preference expressed".
 */
export function prefersReducedMotion(): boolean {
  try {
    return (
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
    );
  } catch {
    return false;
  }
}
