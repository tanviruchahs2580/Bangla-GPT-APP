import React from "react";
import { useLocation } from "react-router-dom";
import { t } from "../i18n";

/**
 * F-001: the app had exactly one boundary, at the root, with no reset key.
 * Any page-level render error replaced the entire app — navigation and all —
 * with the generic error card, and the error state survived navigation, so
 * the only escape was a full reload. This boundary takes a reset key (the
 * current route) and drops the error when the key changes, so moving to
 * another page recovers in place.
 */
export class AppErrorBoundary extends React.Component<
  { children: React.ReactNode; resetKey?: string },
  { error: Error | null; resetKey: string | undefined }
> {
  state = { error: null as Error | null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // The user sees localized copy; the actual error stays reachable for
    // developers and for the optional Sentry hook.
    console.error("render_error", error, info.componentStack);
  }

  static getDerivedStateFromProps(
    props: { resetKey?: string },
    state: { error: Error | null; resetKey: string | undefined },
  ) {
    if (props.resetKey !== state.resetKey) {
      return { error: null, resetKey: props.resetKey };
    }
    return null;
  }

  render() {
    if (this.state.error) {
      return (
        <div className="container" role="alert">
          <div className="card">
            <h2>{t("errorGeneric")}</h2>
            {/* The raw error.message used to render here: untranslated
                internal text in a Bengali-first children's product, and a
                disclosure vector for whatever a dependency puts in a
                message. The user gets the localized copy; the detail goes
                to the console where a developer can still read it. */}
            <p className="muted">{t("errorBoundaryBody")}</p>
            <button
              className="btn btn-primary"
              onClick={() => window.location.reload()}
            >
              {t("retry")}
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * Per-route boundary: the reset key is the route, so a navigation away from
 * a broken page clears the error instead of showing it on every screen.
 */
export function RouteErrorBoundary({
  children,
}: {
  children: React.ReactNode;
}) {
  const location = useLocation();
  return (
    <AppErrorBoundary resetKey={location.pathname}>{children}</AppErrorBoundary>
  );
}
