/**
 * BrandMark — "Shapla Book" vector mark for Bangla GPT Tutor (WAVE-4).
 * Open-book base with a golden shapla (Bangladesh's national flower)
 * rising from the spine + a learning spark — national-scale identity.
 * - Inline SVG, zero assets, ~2KB, no text glyphs (font-independent, so
 *   the mark is pixel-identical in the DOM, favicon and store icons)
 * - Crisp 16px → 512px (single viewBox, filled geometry)
 * - Theme-aware: deep-green badge stays legible in light AND dark
 * - Decorative (aria-hidden by default); pass title for meaningful use
 */
export function BrandMark({
  size = 40,
  title,
}: {
  size?: number;
  title?: string;
}) {
  const gid = "bgpt-brand-grad";
  const fid = "bgpt-shapla-grad";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#16a34a" />
          <stop offset="55%" stopColor="#166534" />
          <stop offset="100%" stopColor="#052e16" />
        </linearGradient>
        <linearGradient id={fid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#fde68a" />
          <stop offset="100%" stopColor="#f59e0b" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" fill={`url(#${gid})`} />
      {/* subtle paper highlight */}
      <ellipse cx="19" cy="10.5" rx="16" ry="6" fill="#ffffff" opacity="0.11" />
      {/* shapla bloom rising from the spine (5 petals) */}
      <g fill={`url(#${fid})`}>
        <path d="M32 11.5 C29 17 28.4 23.4 32 29.8 C35.6 23.4 35 17 32 11.5 Z" />
        <path
          d="M25.4 17 C26 22.8 28.2 26.8 32 29.6 C30.6 23.6 28.4 19.6 25.4 17 Z"
          opacity="0.92"
        />
        <path
          d="M38.6 17 C38 22.8 35.8 26.8 32 29.6 C33.4 23.6 35.6 19.6 38.6 17 Z"
          opacity="0.92"
        />
        <path
          d="M20.2 22.2 C22.2 26.2 25.8 29.2 32 30.8 C29.4 25.6 25.4 23 20.2 22.2 Z"
          opacity="0.8"
        />
        <path
          d="M43.8 22.2 C41.8 26.2 38.2 29.2 32 30.8 C34.6 25.6 38.6 23 43.8 22.2 Z"
          opacity="0.8"
        />
      </g>
      {/* spark of learning */}
      <path
        d="M47.6 9.2 l1.5 3.9 3.9 1.5 -3.9 1.5 -1.5 3.9 -1.5 -3.9 -3.9 -1.5 3.9 -1.5 Z"
        fill="#ffffff"
        opacity="0.95"
      />
      {/* open book */}
      <g fill="#ffffff" opacity="0.97">
        <path d="M32 38.4 C27.8 35.4 21.6 34.6 14.5 36 L14.5 49.4 C21.6 48 27.8 48.8 32 52 Z" />
        <path d="M32 38.4 C36.2 35.4 42.4 34.6 49.5 36 L49.5 49.4 C42.4 48 36.2 48.8 32 52 Z" />
      </g>
      {/* page fold hints */}
      <g
        fill="none"
        stroke="#166534"
        strokeWidth="1.3"
        strokeLinecap="round"
        opacity="0.35"
      >
        <path d="M18 40.2 C23.4 39.4 28 40.1 32 42.4" />
        <path d="M46 40.2 C40.6 39.4 36 40.1 32 42.4" />
      </g>
    </svg>
  );
}

/** Small AI sparkle used beside assistant messages (WP-07). */
export function AiSparkle({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden
      focusable="false"
    >
      <path
        d="M12 2l1.9 5.6L19.5 9l-5.6 1.9L12 16.5l-1.9-5.6L4.5 9l5.6-1.4Z"
        fill="var(--ai)"
      />
      <path
        d="M18.5 14.5l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9Z"
        fill="var(--ai)"
        opacity="0.65"
      />
    </svg>
  );
}
