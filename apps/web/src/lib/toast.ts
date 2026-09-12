/**
 * Minimal toast utility (WP-05/WP-11) — vanilla, zero dependencies.
 * Used ONLY where feedback already exists (save confirmations, errors).
 * No new feature behavior: visual polish over existing flows.
 */
let region: HTMLDivElement | null = null;

function ensureRegion(): HTMLDivElement {
  if (region && document.body.contains(region)) return region;
  region = document.createElement("div");
  region.className = "toast-region";
  region.setAttribute("aria-live", "polite");
  region.setAttribute("role", "status");
  document.body.appendChild(region);
  return region;
}

export function toast(message: string, ms = 2600): void {
  try {
    const host = ensureRegion();
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = message;
    host.appendChild(el);
    window.setTimeout(() => {
      el.style.opacity = "0";
      el.style.transition = "opacity 250ms ease";
      window.setTimeout(() => el.remove(), 260);
    }, ms);
    while (host.children.length > 3) host.firstChild?.remove();
  } catch {
    /* never break the underlying flow */
  }
}
