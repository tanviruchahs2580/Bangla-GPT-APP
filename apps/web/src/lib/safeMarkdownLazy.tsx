import { Suspense, lazy } from "react";

// PERF-001: react-markdown + remark-math + rehype-katex + katex (~390 kB,
// mostly KaTeX fonts/rendering) must not ride the initial bundle. Pages
// render this wrapper; the heavy renderer loads on first use.
const LazyMarkdown = lazy(() =>
  import("./safeMarkdown").then((m) => ({ default: m.SafeMarkdown })),
);

interface Props {
  content: string;
  className?: string;
}

export function SafeMarkdownLazy({ content, className }: Props) {
  return (
    <Suspense
      // FE-FIX (live-region contract): the fallback was `aria-live="polite"`
      // wrapping the RAW partial markdown, and the tutor's stream flushes it
      // every 80 ms — so a screen reader re-announced the half-rendered answer
      // up to a dozen times per turn, which is exactly what the deliberate
      // single-announcement contract (AITutorPage's announcer, asserted by
      // tutorAnnounce.test.tsx) exists to prevent. The fallback is static
      // content that is about to be replaced: it is not a live region.
      fallback={<div className={className}>{content}</div>}
    >
      <LazyMarkdown content={content} className={className} />
    </Suspense>
  );
}
