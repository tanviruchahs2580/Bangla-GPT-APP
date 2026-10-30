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
import { TrendingDown, TrendingUp, X } from "lucide-react";
import { createPortal } from "react-dom";
import { cn } from "../lib/cn";
import { t } from "../i18n";

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
  // Names the dialog from its own heading. `aria-label` was skipped whenever
  // the title was an element rather than a string, leaving those dialogs
  // unnamed; the heading is the name in every case.
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Focus the first real control inside the dialog, not the dialog box:
    // focusing the container left the dialog's OWN first Shift+Tab landing
    // outside the trap, which is the defect this component is documented as
    // having fixed. Fall back to the box (tabIndex={-1}) when it holds no
    // focusable child, so the dialog still receives the next Tab.
    const focusables = boxRef.current?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
    );
    if (focusables && focusables.length > 0) focusables[0].focus();
    else boxRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
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
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    // The backdrop is a mouse dismissal surface, not a control. The rule's
    // remedy for a click handler — `role="button"` + `tabIndex={0}` — was
    // itself the defect here: it added a tab stop OUTSIDE the focus trap (the
    // Shift+Tab escape the trap exists to prevent) and nested a role=dialog
    // inside a role=button. Keyboard dismissal is Escape, handled by the
    // document listener above (and the dialog's own close button), which is
    // where a keyboard user reaches it.
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions -- the backdrop is a mouse dismissal surface, not a control; the keyboard dismissal is Escape (reason above)
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cn("modal", wide && "modal-wide")}
        tabIndex={-1}
      >
        <div className="modal-head">
          <h3 className="modal-title" id={titleId}>
            {title}
          </h3>
          <button
            type="button"
            className="icon-btn modal-close"
            aria-label={t("close")}
            onClick={onClose}
          >
            <X size={18} aria-hidden />
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
 * F-060/A11Y-08: the hint and the error were visible text only — a screen
 * reader heard the role=alert error but could not navigate back to the field
 * it belonged to, and the hint was never announced with the control. The
 * ids are generated here and handed to the wrapped control, so every form
 * built on Field gets the association without each call site repeating it.
 * A non-element child (or several) cannot receive props; those call sites
 * keep their own ids.
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
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy =
    [hint && !error ? hintId : null, error ? errorId : null]
      .filter(Boolean)
      .join(" ") || undefined;
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<Record<string, unknown>>, {
        "aria-describedby":
          describedBy ??
          (children.props as { "aria-describedby"?: string })[
            "aria-describedby"
          ],
        "aria-invalid":
          error || (children.props as { "aria-invalid"?: boolean })[
            "aria-invalid"
          ]
            ? true
            : undefined,
      })
    : children;
  return (
    <div className={cn("field", !!error && "field-error", className)}>
      <label htmlFor={htmlFor}>{label}</label>
      {control}
      {hint && !error && (
        <span className="field-hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="field-error-text" role="alert" id={errorId}>
          {error}
        </span>
      )}
    </div>
  );
}

/**
 * Segmented control over the .chip vocabulary (report period, create kind…).
 *
 * role="group" + aria-pressed, NOT role="tablist": these pick a filter, they
 * have no associated tabpanels, so a tablist role promises arrow-key roving
 * and tabpanel associations the component never delivered (the same bug class
 * keyboardContracts.test.tsx was written for). Plain toggle buttons keep the
 * keyboard promise trivially true — every stop is a native button.
 */
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
    <div className={cn("chips", className)} role="group" aria-label={ariaLabel}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
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

/** Direction of a per-student score trend, as one accessible mark.
 *
 * The trend used to be a bare ▼/▲/– text glyph: it read as iconography, and
 * when it became an icon it lost its meaning to assistive tech. One component
 * now owns the mapping (label in both languages, colour never the only
 * channel) so the two teacher screens cannot drift apart. */
export function TrendMark({ trend }: { trend: "up" | "down" | "flat" }) {
  if (trend === "down") {
    return (
      <span
        className="trend-mark trend-down"
        role="img"
        aria-label={t("trendFalling")}
      >
        <TrendingDown size={14} aria-hidden />
      </span>
    );
  }
  if (trend === "up") {
    return (
      <span
        className="trend-mark trend-up"
        role="img"
        aria-label={t("trendRising")}
      >
        <TrendingUp size={14} aria-hidden />
      </span>
    );
  }
  return (
    <span
      className="trend-mark trend-flat"
      role="img"
      aria-label={t("trendSteady")}
    >
      {"–"}
    </span>
  );
}
