import {
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "../lib/cn";
import { parseDigits } from "../lib/digits";
import { t } from "../i18n";
import { BrandMark } from "./BrandMark";

type Variant = "primary" | "teal" | "ghost" | "soft" | "danger" | "default";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "btn btn-primary",
  teal: "btn btn-teal",
  ghost: "btn btn-ghost",
  soft: "btn btn-soft",
  danger: "btn btn-danger",
  default: "btn",
};

const SIZES: Record<Size, string> = { sm: "btn-sm", md: "", lg: "btn-lg" };

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  block?: boolean;
  loading?: boolean;
}

export function Button({
  variant = "default",
  size = "md",
  block,
  loading,
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      aria-busy={loading || undefined}
      className={cn(
        VARIANTS[variant],
        SIZES[size],
        block && "btn-block",
        loading && "btn-loading",
        className,
      )}
      {...rest}
    />
  );
}

export function Card({
  children,
  className,
  title,
  action,
}: {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className={cn("card", className)}>
      {(title || action) && (
        <div className="row-flex card-head-row">
          <div className="card-title card-title-flush">{title}</div>
          <div className="card-action">{action}</div>
        </div>
      )}
      {children}
    </section>
  );
}

export function Badge({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "ok" | "warn" | "teal" | "ai";
}) {
  return (
    <span
      className={cn(
        "badge",
        tone === "ok" && "badge-ok",
        tone === "warn" && "badge-warn",
        tone === "teal" && "badge-teal",
        tone === "ai" && "badge-ai",
      )}
    >
      {children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  // default label comes from i18n instead of hardcoded English.
  return (
    <span role="status" aria-live="polite">
      <span className="visually-hidden">{label ?? t("loading")}</span>
      <span className="skeleton spinner-dot" aria-hidden />
    </span>
  );
}

export function ProgressRing({
  value,
  size = 84,
  label,
}: {
  value: number;
  size?: number;
  label?: ReactNode;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  const inner = size - 14;
  return (
    <div
      className="ring ring-draw"
      style={{
        width: size,
        height: size,
        ["--p" as string]: clamped,
        flexShrink: 0,
      }}
      role="img"
      aria-label={`${Math.round(clamped)}%`}
    >
      <div className="ring-inner" style={{ width: inner, height: inner }}>
        {label ?? `${Math.round(clamped)}%`}
      </div>
    </div>
  );
}

export function Stat({ value, label }: { value: ReactNode; label: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export function Row({
  title,
  sub,
  trailing,
  onClick,
}: {
  title: ReactNode;
  sub?: ReactNode;
  trailing?: ReactNode;
  onClick?: () => void;
}) {
  const content = (
    <>
      <div className="row-main">
        <div className="row-title">{title}</div>
        {sub && <div className="row-sub">{sub}</div>}
      </div>
      {trailing}
    </>
  );
  if (onClick) {
    return (
      <button className="row row-action" onClick={onClick}>
        {content}
      </button>
    );
  }
  return <div className="row">{content}</div>;
}

export function EmptyState({
  title,
  sub,
  action,
}: {
  title: ReactNode;
  sub?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="center empty-state empty-pad">
      <div className="empty-mark" aria-hidden>
        <BrandMark size={56} />
      </div>
      <div className="empty-title">{title}</div>
      {sub && <p className="muted empty-sub">{sub}</p>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}

/* Shared primitives: one focus-trapped modal, one skeleton
   vocabulary, one form field / segmented / avatar pattern for
   every page. */

/** A failed query, said out loud.
 *
 * Pages that branched only on `isLoading` fell through to their empty state on
 * failure, so an outage read as "you have no homework" / "there are no chapters
 * for this subject" -- a confident, wrong statement the student cannot tell
 * apart from the truth, and one that makes them skip work that does exist.
 * This is the retryable alternative, matching the treatment each parent
 * section already uses.
 */
export function LoadError({
  message,
  onRetry,
  className,
}: {
  message?: ReactNode;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div className={cn("center stack", className)}>
      <p className="error m-0" role="alert">
        {message ?? t("errorGeneric")}
      </p>
      {onRetry && (
        <button className="btn btn-sm btn-ghost" onClick={onRetry}>
          {t("retry")}
        </button>
      )}
    </div>
  );
}

/** Accessible modal dialog: portal, focus trap, Esc to close,
    scroll lock, focus restore. Styling reuses .modal-backdrop/.modal. */
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  // The parent re-creates onClose on every render (it is usually an inline
  // arrow). Reading it through a ref keeps the effect below tied to `open`
  // alone: depending on the handler made every keystroke re-run the cleanup
  // (restoring focus to the opener and re-toggling body overflow), which
  // ejected the caret from a textarea after its first character.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // focus the dialog itself so Tab cycles start inside
    boxRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !boxRef.current) return;
      const focusables = boxRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = prevOverflow;
      restoreRef.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  return createPortal(
    <div
      className="modal-backdrop"
      // Purely dismissive chrome: clicking it closes, but it is NOT an
      // interactive element (role=presentation). It used to carry
      // role="button" + tabIndex + onKeyDown, which made a SPACE typed inside
      // the dialog's own textarea bubble here and close the dialog
      // mid-sentence (keydown handlers see their descendants' events).
      // Dismissal is the close button and Escape (handled by the effect
      // above), both keyboard-reachable.
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        className={cn("modal", wide && "modal-wide")}
        tabIndex={-1}
      >
        <div className="modal-head">
          <h3 className="modal-title">{title}</h3>
          <button
            type="button"
            className="icon-btn modal-close"
            aria-label={t("close")}
            onClick={onClose}
          >
            ✕
          </button>
        </div>
        {children}
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/** Shimmer placeholder. `w`/`h` are layout dimensions (not theme values). */
export function Skeleton({
  w,
  h,
  variant,
  className,
}: {
  w?: number | string;
  h?: number | string;
  variant?: "text" | "card" | "row" | "avatar";
  className?: string;
}) {
  const variantClass =
    variant === "card"
      ? "skeleton-card"
      : variant === "row"
        ? "skeleton-list-row"
        : variant === "avatar"
          ? "skeleton-avatar"
          : undefined;
  return (
    <div
      aria-hidden
      className={cn("skeleton", variantClass, className)}
      style={{ width: w, height: h }}
    />
  );
}

/** Label + control + error text, matching the .field contract.
 *
 * AUD-G-11: the error text used to be a sibling with no programmatic link to
 * the input, so a screen-reader user heard "unlabelled edit field" and never
 * the reason it was rejected. The single control passed as `children` is now
 * given the id, `aria-invalid` and `aria-describedby` the error needs, so any
 * form built from this primitive is wired by construction.
 */
export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
  className,
}: {
  label: ReactNode;
  htmlFor?: string;
  error?: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const autoId = useId();
  const controlId = htmlFor ?? autoId;
  const errorId = `${controlId}-error`;
  const hintId = `${controlId}-hint`;
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<Record<string, unknown>>, {
        id: (children.props as { id?: string }).id ?? controlId,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": error ? errorId : hint ? hintId : undefined,
      })
    : children;
  return (
    <div className={cn("field", !!error && "field-error", className)}>
      <label htmlFor={controlId}>{label}</label>
      {control}
      {hint && !error && (
        <span className="field-hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="field-error-text" id={errorId} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

/** Number field that accepts Bengali and ASCII digits (AUD-G-11).
 *
 * `type="number"` refuses Bengali digits at the keyboard level - nothing
 * arrives in `onChange` - so a Bangla keyboard user cannot fill a numeric
 * field at all. This renders a text control with a numeric keypad hint and
 * normalises ০-৯ to ASCII before parsing.
 */
export function NumberInput({
  value,
  onValue,
  min,
  max,
  fallback,
  id,
  className,
  ...rest
}: {
  value: number;
  onValue: (value: number) => void;
  min?: number;
  max?: number;
  /** Value used when the field is emptied or unparsable. */
  fallback?: number;
  id?: string;
  className?: string;
} & Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "value" | "onChange" | "type" | "id" | "className"
>) {
  const commit = (raw: string) => {
    const parsed = parseDigits(raw, Number.NaN);
    if (Number.isNaN(parsed)) {
      onValue(fallback ?? min ?? 0);
      return;
    }
    const lower = min ?? Number.NEGATIVE_INFINITY;
    const upper = max ?? Number.POSITIVE_INFINITY;
    onValue(Math.min(upper, Math.max(lower, parsed)));
  };
  return (
    <input
      {...rest}
      id={id}
      className={cn("input", className)}
      type="text"
      inputMode="numeric"
      // Both scripts in the pattern so the browser's own validity check and
      // the on-screen keypad agree with what we accept.
      pattern="[0-9০-৯]*"
      value={String(value)}
      onChange={(e) => commit(e.target.value)}
    />
  );
}

/** Segmented control over the .chip vocabulary (quiz tabs, class picker…). */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  options: Array<{ value: T; label: ReactNode }>;
  value: T;
  onChange: (v: T) => void;
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <div
      className={cn("chips", className)}
      role="tablist"
      aria-label={ariaLabel}
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={o.value === value}
          className={cn("chip", o.value === value && "active")}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Initial-based avatar with brand-consistent tones. */
export function Avatar({
  name,
  size = "md",
  tone = "brand",
}: {
  name: string;
  size?: "sm" | "md" | "lg" | "xl";
  tone?: "brand" | "teal" | "ai";
}) {
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  return (
    <span
      aria-hidden
      className={cn(
        "avatar",
        size !== "md" && `avatar-${size}`,
        tone !== "brand" && `avatar-${tone}`,
      )}
    >
      {initial}
    </span>
  );
}
