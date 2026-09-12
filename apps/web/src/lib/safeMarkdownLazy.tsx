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
      fallback={
        <div className={className} aria-live="polite">
          {content}
        </div>
      }
    >
      <LazyMarkdown content={content} className={className} />
    </Suspense>
  );
}
