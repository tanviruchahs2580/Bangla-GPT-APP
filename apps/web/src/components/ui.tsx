import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/cn";

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
}

export function Button({
  variant = "default",
  size = "md",
  block,
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        VARIANTS[variant],
        SIZES[size],
        block && "btn-block",
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
  style,
}: {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
  action?: ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <section className={cn("card", className)} style={style}>
      {(title || action) && (
        <div className="row-flex" style={{ marginBottom: "8px" }}>
          <div className="card-title" style={{ margin: 0 }}>
            {title}
          </div>
          <div style={{ marginLeft: "auto" }}>{action}</div>
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
  tone?: "default" | "ok" | "warn" | "teal";
}) {
  return (
    <span
      className={cn(
        "badge",
        tone === "ok" && "badge-ok",
        tone === "warn" && "badge-warn",
        tone === "teal" && "badge-teal",
      )}
    >
      {children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span role="status" aria-live="polite">
      <span className="visually-hidden">{label ?? "Loading…"}</span>
      <span
        className="skeleton"
        style={{
          display: "inline-block",
          width: "1.1em",
          height: "1.1em",
          verticalAlign: "middle",
        }}
      />
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
      className="ring"
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
      <button
        className="row"
        style={{
          width: "100%",
          background: "none",
          border: "none",
          borderBottom: "1px solid var(--line)",
          textAlign: "left",
          color: "inherit",
          cursor: "pointer",
          font: "inherit",
        }}
        onClick={onClick}
      >
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
    <div
      className="center"
      style={{ padding: "var(--space-6) var(--space-4)" }}
    >
      <div style={{ fontSize: "2.2rem", marginBottom: "8px" }}>📘</div>
      <div style={{ fontWeight: 700 }}>{title}</div>
      {sub && (
        <div className="muted" style={{ marginTop: "4px" }}>
          {sub}
        </div>
      )}
      {action && <div style={{ marginTop: "16px" }}>{action}</div>}
    </div>
  );
}
