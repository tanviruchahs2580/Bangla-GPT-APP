import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/cn";
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
  return (
    <span role="status" aria-live="polite">
      <span className="visually-hidden">{label ?? "Loading…"}</span>
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
      {sub && <div className="muted empty-sub">{sub}</div>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}
