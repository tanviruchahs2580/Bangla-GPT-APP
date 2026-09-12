/**
 * BrandMark — vector brand monogram for Bangla GPT Tutor (WP-02).
 * Geometric open-book + graduation-cap motif with "বাং" identity.
 * - Inline SVG, zero assets, ≤2KB
 * - Crisp 16px → 512px (single viewBox, vector shapes + text)
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
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" fill={`url(#${gid})`} />
      {/* subtle paper highlight */}
      <ellipse cx="20" cy="12" rx="18" ry="7" fill="#ffffff" opacity="0.12" />
      {/* open book motif */}
      <g
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.95"
      >
        <path d="M32 14 L14 20 v22 l18 -6 18 6 V20 Z" />
        <path d="M32 14 v22" opacity="0.85" />
      </g>
      {/* graduation cap accent */}
      <g fill="#fde68a" opacity="0.95">
        <path d="M46 12 l7 3 -7 3 -7 -3 Z" />
        <rect x="51.4" y="15.6" width="1.8" height="6" rx="0.9" />
      </g>
      {/* বাং monogram */}
      <text
        x="32"
        y="55"
        textAnchor="middle"
        fontFamily="'Noto Sans Bengali','Hind Siliguri',sans-serif"
        fontWeight={800}
        fontSize="17"
        fill="#ffffff"
      >
        বাং
      </text>
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
