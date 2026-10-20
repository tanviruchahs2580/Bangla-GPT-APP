import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { markdownComponents } from "./markdownComponents";

/**
 * G-19: the math pipeline, deferred to its own chunk.
 *
 * react-markdown + remark-math + rehype-katex + KaTeX is ~ten times the size of
 * the markdown core, and almost no Bangla answer contains math. Importing it
 * statically meant every student paid for it twice: once as download, once as
 * main-thread compile -- measured as the largest task (606-930 ms at 6x CPU
 * throttle) on the tutor route, on a transcript with no maths in it at all.
 * `safeMarkdown.tsx` now renders plain content with the markdown core and
 * suspends into this module only when the answer carries a math delimiter.
 *
 * Props and markup are identical to the plain path, so a container that
 * switches between them (an answer that gains a formula mid-stream) does not
 * change layout or lose the class name.
 */
const REMARK = [remarkMath];
const REHYPE = [rehypeKatex];

export default function MathMarkdown({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={REMARK}
        rehypePlugins={REHYPE}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
