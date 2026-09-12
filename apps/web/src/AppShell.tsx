import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  BookOpen,
  Download,
  GraduationCap,
  Home,
  User,
  Zap,
  Languages,
  Moon,
  Sun,
  LogOut,
} from "lucide-react";
import { useAuth, ROLE_HOME } from "./AuthContext";
import { exitImpersonation, isImpersonating } from "./api";
import { NotificationBell } from "./components/NotificationBell";
import { BrandMark } from "./components/BrandMark";
import { SearchBox } from "./components/SearchBox";
import { getLang, onLangChange, setLang, t } from "./i18n";
import { toggleTheme, currentTheme } from "./lib/theme";
import {
  canInstall,
  onInstallChange,
  promptInstall,
} from "./lib/installPrompt";

const STUDENT_NAV = [
  { to: "/student", end: true, label: "home", icon: Home },
  { to: "/student/learn", end: false, label: "learn", icon: BookOpen },
  { to: "/student/tutor", end: false, label: "aiTutor", icon: Zap },
  { to: "/student/quiz", end: false, label: "quiz", icon: GraduationCap },
  { to: "/student/me", end: false, label: "me", icon: User },
] as const;

export function OfflineBanner() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  if (online) return null;
  return (
    <div className="offline-banner" role="status">
      {t("offlineBanner")}
    </div>
  );
}

export function ImpersonationBanner() {
  const { me } = useAuth();
  const [ending, setEnding] = useState(false);
  if (!isImpersonating()) return null;
  return (
    <div role="status" className="impersonation-banner">
      <span>{t("actingAs", { name: me?.name ?? me?.email ?? "?" })}</span>
      <button
        className="small"
        disabled={ending}
        onClick={async () => {
          setEnding(true);
          await exitImpersonation();
          window.location.assign("/");
        }}
      >
        {t("exitImpersonation")}
      </button>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, signOut } = useAuth();
  const [, force] = useState(0);
  useEffect(() => onLangChange(() => force((n) => n + 1)), []);
  const navigate = useNavigate();
  const dark = currentTheme() === "dark";
  // S1.14: show the install affordance only when Chromium offers it
  const [installable, setInstallable] = useState(canInstall());
  useEffect(() => onInstallChange(() => setInstallable(canInstall())), []);
  const isStaff = !!me && me.role !== "student";
  const roleHome = (me && ROLE_HOME[me.role]) || "/";

  return (
    <div className={isStaff ? "shell has-sidebar" : "shell"}>
      <OfflineBanner />
      <ImpersonationBanner />
      <header className="topbar">
        <button
          className="brand brand-reset"
          onClick={() => navigate(me ? `/` : "/login")}
          aria-label={t("brandHome")}
        >
          <span className="brand-mark" aria-hidden>
            <BrandMark size={30} />
          </span>
          {t("appName")}
        </button>
        {me?.role === "student" && <SearchBox />}
        <nav className="row-flex topbar-actions" aria-label="Settings">
          {me && (
            <span className="muted muted-sm topbar-user">
              {me.name ?? me.email}
            </span>
          )}
          {installable && (
            <button
              className="icon-btn"
              aria-label={t("installApp")}
              onClick={() => void promptInstall()}
            >
              <Download size={18} aria-hidden />
            </button>
          )}
          {me && <NotificationBell />}
          <button
            className="icon-btn"
            aria-label="Switch language"
            onClick={() => {
              const next = getLang() === "bn" ? "en" : "bn";
              setLang(next);
              document.documentElement.setAttribute("lang", next);
              // Pages render t() during render; remount so every string updates.
              navigate(0);
            }}
          >
            <Languages size={18} aria-hidden />
          </button>
          <button
            className="icon-btn"
            aria-label="Toggle theme"
            onClick={() => toggleTheme()}
          >
            {dark ? (
              <Sun size={18} aria-hidden />
            ) : (
              <Moon size={18} aria-hidden />
            )}
          </button>
          {me && (
            <button
              className="icon-btn"
              aria-label={t("logout")}
              onClick={signOut}
            >
              <LogOut size={18} aria-hidden />
            </button>
          )}
        </nav>
      </header>

      {isStaff && (
        <div className="shell-body">
          <aside className="sidebar" aria-label={t("dashboard")}>
            <NavLink
              to={roleHome}
              end
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              {t("dashboard")}
            </NavLink>
            <NavLink
              to="/status"
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              {t("statusPage")}
            </NavLink>
          </aside>
          <div className="shell-content">{children}</div>
        </div>
      )}

      {!isStaff && <>{children}</>}

      {me?.role === "student" && (
        <nav className="bottombar" aria-label="Primary">
          {STUDENT_NAV.map(({ to, end, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                isActive ? "bnav-item active" : "bnav-item"
              }
            >
              <Icon size={22} aria-hidden />
              <span>{t(label)}</span>
              <span className="bnav-dot" aria-hidden />
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  );
}
