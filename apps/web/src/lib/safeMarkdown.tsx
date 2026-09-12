import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

interface Props {
  content: string;
  className?: string;
}

// Sanitize raw HTML tags in markdown source (XSS guard).
// react-markdown without rehype-raw does not render HTML tags,
// but we still strip script-like content at source level.
function sanitize(source: string): string {
  return source
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, "")
    .replace(/on\w+\s*=\s*["'][^"']*["']/gi, "");
}

export function SafeMarkdown({ content, className }: Props) {
  const safe = sanitize(content);
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {safe}
      </ReactMarkdown>
    </div>
  );
}
