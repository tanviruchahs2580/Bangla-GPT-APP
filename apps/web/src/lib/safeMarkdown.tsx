import ReactMarkdown, { type Components } from "react-markdown";
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

/**
 * Only these schemes may appear in a link the model produced.
 *
 * F-128: a markdown link inside a tutor answer rendered exactly like a
 * citation. The tutor cites NCTB sources as chips, so a model that emitted
 * `[text](https://evil.example.com/steal)` put an attacker-controlled,
 * indistinguishable-from-trusted link next to two real ones — in a
 * children's product, where the model's output is treated as authoritative.
 * It also navigated in the same tab, so clicking it left the SPA and lost
 * the session (F-129).
 */
const ALLOWED_SCHEMES = ["http:", "https:", "mailto:"];

function isSafeHref(href: string | undefined): boolean {
  if (!href) return false;
  // Relative links are same-origin and fine.
  if (href.startsWith("/") || href.startsWith("#")) return true;
  try {
    return ALLOWED_SCHEMES.includes(new URL(href).protocol);
  } catch {
    // Not parseable as an absolute URL and not relative: refuse rather than
    // guess. `javascript:alert(1)` and `data:text/html,...` land here.
    return false;
  }
}

const components: Partial<Components> = {
  a({ href, children, ...rest }) {
    if (!isSafeHref(href)) {
      // Render the text, drop the link. Silently keeping an un-clickable
      // span would look like a rendering bug; saying so is honest.
      return (
        <span
          className="blocked-link"
          title="This link was removed by the assistant."
        >
          {children}
        </span>
      );
    }
    const external = /^https?:/i.test(href ?? "");
    return (
      <a
        {...rest}
        href={href}
        {...(external
          ? { target: "_blank", rel: "noopener noreferrer nofollow" }
          : {})}
      >
        {children}
        {external ? <span className="sr-only"> (external link)</span> : null}
      </a>
    );
  },
  img({ src, alt, ...rest }) {
    // The model cannot cause a request to an arbitrary host by embedding an
    // image; drop it and keep the alt text.
    if (typeof src !== "string" || !isSafeHref(src)) {
      return <span className="blocked-link">{alt ?? ""}</span>;
    }
    return <img {...rest} src={src} alt={alt ?? ""} loading="lazy" />;
  },
};

export function SafeMarkdown({ content, className }: Props) {
  const safe = sanitize(content);
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {safe}
      </ReactMarkdown>
    </div>
  );
}
