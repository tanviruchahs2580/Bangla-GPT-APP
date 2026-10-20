import { lazy, memo, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import { markdownComponents } from "./markdownComponents";

interface Props {
  content: string;
  className?: string;
}

/**
 * The math pipeline (remark-math + rehype-katex + KaTeX, ~ten times the
 * markdown core) lives in its own chunk and is fetched only when the answer
 * actually carries a formula -- see `mathMarkdown.tsx`. Everything else about
 * the renderer is shared: the link/image rules come from
 * `markdownComponents.tsx`, so there is one implementation of the security
 * boundary, not two.
 */
const MathMarkdown = lazy(() => import("./mathMarkdown"));

/**
 * G-19: the math pipeline is opt-in per answer.
 *
 * Detecting the delimiter is what keeps the deferred chunk honest: source
 * without a delimiter cannot render differently without the plugin
 * (MathNode never fires), and with no plugin the tokenizer does not walk the
 * tree either.
 */
const MATH_DELIMITER = /\$|\\\(|\\\[|\\begin\{/;

/**
 * Memoized on its props: a bubble whose `content` did not change must not
 * re-parse. The tutor transcript re-renders per streamed token.
 */
export const SafeMarkdown = memo(function SafeMarkdown({
  content,
  className,
}: Props) {
  if (!MATH_DELIMITER.test(content)) {
    return (
      <div className={className}>
        <ReactMarkdown components={markdownComponents}>{content}</ReactMarkdown>
      </div>
    );
  }
  return (
    <Suspense
      fallback={
        // Same copy as `safeMarkdownLazy`'s first-paint fallback: the raw
        // answer, so a slow chunk never shows an empty bubble.
        <div className={className}>{content}</div>
      }
    >
      <MathMarkdown content={content} className={className} />
    </Suspense>
  );
});
