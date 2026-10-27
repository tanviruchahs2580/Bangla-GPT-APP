import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell } from "lucide-react";
import { getNotifications, markNotificationRead } from "../api";
import type { NotificationItem } from "../api";
import { t } from "../i18n";

/** Backend links are API-shaped; map to the real UI routes. */
const KIND_ROUTE: Record<string, string> = {
  assignment: "/student/quiz",
  shorttest: "/student/quiz",
  support_plan: "/student/quiz",
  parent_link: "/parent",
};
const UI_PREFIXES = ["/student", "/parent", "/teacher", "/admin", "/school"];

function targetOf(n: NotificationItem): string | null {
  if (n.link && UI_PREFIXES.some((p) => n.link!.startsWith(p))) return n.link;
  return KIND_ROUTE[n.kind] ?? null;
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
  const boxRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const refresh = useCallback(async () => {
    try {
      const res = await getNotifications();
      setItems(res.items);
      setUnread(res.unread_count);
    } catch {
      /* silent: the bell is best-effort chrome */
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
        aria-label={t("notifications")}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => {
          setOpen((o) => !o);
          if (!open) void refresh();
        }}
      >
        <Bell size={18} aria-hidden />
        {unread > 0 && (
          <span className="notif-badge" aria-hidden>
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div
          ref={panelRef}
          className="notif-panel"
          role="menu"
          aria-label={t("notifications")}
        >
          <div className="notif-head">{t("notifications")}</div>
          {items.length === 0 && (
            <div className="notif-empty muted">{t("notifEmpty")}</div>
          )}
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
      )}
    </div>
  );
}
