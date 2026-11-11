import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell } from "lucide-react";
import { getNotifications, markNotificationRead } from "../api";
import type { NotificationItem } from "../api";
import { formatNumber, t } from "../i18n";
import { uiPathOf } from "../lib/safeHref";

/** Backend links are API-shaped; map to the real UI routes. */
const KIND_ROUTE: Record<string, string> = {
  assignment: "/student/quiz",
  shorttest: "/student/quiz",
  support_plan: "/student/quiz",
  parent_link: "/parent",
};

/** FE-FIX (trust rule): the shared `lib/safeHref` allowlist now also owns the
 *  prefix list this component used to keep privately, so the search dropdown
 *  validates server hrefs the same way. */
function targetOf(n: NotificationItem): string | null {
  return uiPathOf(n.link) ?? KIND_ROUTE[n.kind] ?? null;
}

/** Backend sends snake_case wire codes (notif_parent_linked); dict keys are
 * camelCase (notifParentLinked). Map before lookup, fall back to the raw code. */
function dictKeyOf(code: string): string {
  return code.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
}

function textOf(n: NotificationItem): string {
  const key = dictKeyOf(n.code) as Parameters<typeof t>[0];
  const text = t(key, n.params);
  // t() echoes the dict key for unknown codes; show the raw wire code instead.
  return text && text !== key ? text : n.code;
}

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  // FE-FIX (numerals): the capped count is still a quantity, so its digit
  // follows the active language like every other number — "৯+" under bn, not a
  // Latin "9+" inside Bangla copy.
  const countText = unread > 9 ? `${formatNumber(9)}+` : formatNumber(unread);
  // FE-FIX-004: a failed fetch was swallowed by an empty catch, so the panel
  // rendered "এখন কোনো নোটিফিকেশন নেই" — a claim about the student's account
  // produced by a request that never answered — and the unread badge vanished,
  // hiding a freshly assigned quiz. `loaded` distinguishes "we read the answer
  // and it said zero" from "we never read an answer".
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const refresh = useCallback(async () => {
    try {
      const res = await getNotifications();
      setItems(res.items);
      setUnread(res.unread_count);
      setLoaded(true);
      setError(null);
    } catch {
      // The last known list is kept on screen (stale but true when it was
      // read); only the count is withheld while it is unverified.
      setError(t("notifLoadFailed"));
    }
  }, []);

  useEffect(() => {
    void refresh();
    // FE-09: a phone in a backpack kept polling every minute — battery and
    // mobile data burned by a screen nobody is looking at. The interval
    // runs only while the page is visible; visibilitychange fires an
    // immediate refresh on return so the badge is not stale on unlock.
    let id: number | undefined;
    const start = () => {
      if (id === undefined)
        id = window.setInterval(() => void refresh(), 60_000);
    };
    const stop = () => {
      if (id !== undefined) {
        window.clearInterval(id);
        id = undefined;
      }
    };
    start();
    document.addEventListener("visibilitychange", onVisible);
    function onVisible() {
      if (document.hidden) stop();
      else {
        void refresh();
        start();
      }
    }
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      stop();
    };
  }, [refresh]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const closeAndRestore = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  // role="menu" is a keyboard CONTRACT, not a styling hook: opening moves
  // focus to the first item, arrows/Home/End traverse, Escape closes and
  // restores focus to the trigger, and Tab out closes the menu. Before
  // this, the panel announced a menu to screen readers and then ignored
  // every key an APG menu promises.
  useEffect(() => {
    if (!open) return;
    const items = () =>
      Array.from(
        panelRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ??
          [],
      );
    const first = items()[0];
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      const all = items();
      if (all.length === 0) {
        if (e.key === "Escape" || e.key === "Tab") closeAndRestore();
        return;
      }
      const at = all.indexOf(document.activeElement as HTMLElement);
      let next: HTMLElement | null = null;
      if (e.key === "Escape") {
        e.preventDefault();
        closeAndRestore();
        return;
      }
      if (e.key === "Tab") {
        // Focus leaves the menu: close it, let the browser move focus.
        setOpen(false);
        return;
      }
      if (e.key === "ArrowDown") next = all[(at + 1 + all.length) % all.length];
      else if (e.key === "ArrowUp")
        next = all[(at - 1 + all.length) % all.length];
      else if (e.key === "Home") next = all[0];
      else if (e.key === "End") next = all[all.length - 1];
      if (next) {
        e.preventDefault();
        next.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, closeAndRestore]);

  const openItem = async (n: NotificationItem) => {
    setOpen(false);
    if (!n.read_at) {
      try {
        await markNotificationRead(n.id);
        setUnread((u) => Math.max(0, u - 1));
      } catch {
        /* navigation proceeds regardless */
      }
    }
    const to = targetOf(n);
    if (to) void navigate(to);
  };

  return (
    <div ref={boxRef} className="notif-wrap">
      <button
        ref={triggerRef}
        className="icon-btn"
        // A11Y-03/F-168: the count lived only in the aria-hidden badge, so a
        // screen-reader student never learned a quiz had been assigned. The
        // count sits OUTSIDE parentheses in the name: axe's
        // label-content-name-mismatch strips parentheticals from both sides
        // before comparing, so "Notifications (2)" against a visible "2"
        // badge fails WCAG 2.5.3's label-in-name check.
        aria-label={
          error && !loaded
            ? `${t("notifications")} — ${t("notifLoadFailed")}`
            : unread > 0
              ? `${t("notifications")}: ${countText}`
              : t("notifications")
        }
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => {
          setOpen((o) => !o);
          if (!open) void refresh();
        }}
      >
        <Bell size={18} aria-hidden />
        {error && !loaded ? (
          /* FE-FIX-004: the count is unknown, not zero. An error mark keeps the
             bell from looking like "nothing waiting" until the retry answers. */
          <span className="notif-badge notif-badge-error" aria-hidden>
            !
          </span>
        ) : unread > 0 ? (
          <span className="notif-badge" aria-hidden>
            {countText}
          </span>
        ) : null}
      </button>
      {open && (
        /* FE-FIX-004: the head, the honest empty/error line and the retry sit
           OUTSIDE the role="menu" element — a menu may only own menu items, and
           an alert inside it is an ARIA contract violation the sweeps flag.
           The keyboard contract is unchanged: the same ref is queried for
           menuitems, and the items are still the menu's only children. */
        <div ref={panelRef} className="notif-panel">
          <div className="notif-head">{t("notifications")}</div>
          {error && (
            <div className="notif-error" role="alert">
              <span>{error}</span>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => void refresh()}
              >
                {t("retry")}
              </button>
            </div>
          )}
          {items.length === 0 && !error && (
            <div className="notif-empty muted">{t("notifEmpty")}</div>
          )}
          <div
            className="notif-menu"
            role="menu"
            aria-label={t("notifications")}
          >
            {items.map((n) => (
              <button
                key={n.id}
                role="menuitem"
                className={n.read_at ? "notif-item" : "notif-item unread"}
                onClick={() => void openItem(n)}
              >
                <span>{textOf(n)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
