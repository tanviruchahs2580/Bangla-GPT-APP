/**
 * Minimal toast utility (/) — vanilla, zero dependencies.
 * Used ONLY where feedback already exists (save confirmations, errors).
 * No new feature behavior: visual polish over existing flows.
 *
 * E1 (interaction integrity): toasts now carry a tone ("info" | "success" |
 * "danger") with a leading icon, and the exit is owned by CSS motion tokens
 * (the .toast-out keyframe) instead of an inline opacity transition. The call
 * shape is backward-compatible: `toast(message)` still works and the tone
 * defaults to "info".
 *
 * The icons mirror lucide-react's Info / CheckCircle2 / AlertTriangle glyphs.
 * This module is deliberately React-free (header above), so it cannot render
 * the lucide components themselves; the node lists below are the path data of
 * those three lucide icons (ISC), drawn with lucide's own SVG attributes. If
 * one changes upstream, update the matching entry here.
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

export type ToastTone = "info" | "success" | "danger";

/** lucide icon bodies on the 24×24 grid, keyed by toast tone. */
const ICON_NODES: Record<ToastTone, Array<[string, Record<string, string>]>> = {
  // Info
  info: [
    ["circle", { cx: "12", cy: "12", r: "10" }],
    ["path", { d: "M12 16v-4" }],
    ["path", { d: "M12 8h.01" }],
  ],
  // CheckCircle2 (lucide's circle-check)
  success: [
    ["circle", { cx: "12", cy: "12", r: "10" }],
    ["path", { d: "m16 9-5.5 5.5L8 12" }],
  ],
  // AlertTriangle (lucide's triangle-alert)
  danger: [
    [
      "path",
      {
        d: "m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3",
      },
    ],
    ["path", { d: "M12 9v4" }],
    ["path", { d: "M12 17h.01" }],
  ],
};

function iconEl(tone: ToastTone): SVGElement {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  for (const [attr, value] of Object.entries({
    viewBox: "0 0 24 24",
    width: "18",
    height: "18",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  })) {
    svg.setAttribute(attr, value);
  }
  // Decoration only: the region's aria-live carries the message, so the icon
  // must stay out of the accessible name.
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.classList.add("toast-icon");
  for (const [tag, attrs] of ICON_NODES[tone]) {
    const child = document.createElementNS(NS, tag);
    for (const [attr, value] of Object.entries(attrs)) {
      child.setAttribute(attr, value);
    }
    svg.appendChild(child);
  }
  return svg;
}

export function toast(
  message: string,
  ms = 2600,
  tone: ToastTone = "info",
): void {
  try {
    const host = ensureRegion();
    const el = document.createElement("div");
    el.className = `toast toast-${tone}`;
    el.appendChild(iconEl(tone));
    el.appendChild(document.createTextNode(message));
    host.appendChild(el);
    window.setTimeout(() => {
      // Exit is the .toast-out CSS animation on the motion tokens; the element
      // is removed when it finishes. The timeout is a backstop for environments
      // that never fire animationend (jsdom, a detached node) — --m-fast is
      // 150ms, so 260ms clears every real run.
      const done = () => el.remove();
      el.classList.add("toast-out");
      el.addEventListener("animationend", done, { once: true });
      window.setTimeout(done, 260);
    }, ms);
    while (host.children.length > 3) host.firstChild?.remove();
  } catch {
    /* never break the underlying flow */
  }
}
