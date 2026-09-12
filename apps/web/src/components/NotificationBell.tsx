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
    const id = setInterval(() => void refresh(), 60_000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

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
    if (to) navigate(to);
  };

  return (
    <div ref={boxRef} className="notif-wrap">
      <button
        className="icon-btn"
        aria-label={t("notifications")}
        aria-expanded={open}
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
