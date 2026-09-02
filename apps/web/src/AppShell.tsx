import { useEffect, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  BookOpen,
  GraduationCap,
  Home,
  User,
  Zap,
  Languages,
  Moon,
  Sun,
  LogOut,
} from 'lucide-react'
import { useAuth } from './AuthContext'
import { getLang, onLangChange, setLang, t } from './i18n'
import { toggleTheme, currentTheme } from './lib/theme'

const STUDENT_NAV = [
  { to: '/student', end: true, label: 'home', icon: Home },
  { to: '/student/learn', end: false, label: 'learn', icon: BookOpen },
  { to: '/student/tutor', end: false, label: 'aiTutor', icon: Zap },
  { to: '/student/quiz', end: false, label: 'quiz', icon: GraduationCap },
  { to: '/student/me', end: false, label: 'me', icon: User },
] as const

export function OfflineBanner() {
  const [online, setOnline] = useState(navigator.onLine)
  useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [])
  if (online) return null
  return (
    <div className="offline-banner" role="status">
      {t('offlineBanner')}
    </div>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, signOut } = useAuth()
  const [, force] = useState(0)
  useEffect(() => onLangChange(() => force((n) => n + 1)), [])
  const navigate = useNavigate()
  const dark = currentTheme() === 'dark'

  return (
    <div className="shell">
      <OfflineBanner />
      <header className="topbar">
        <button
          className="brand"
          style={{ background: 'none', border: 'none', cursor: 'pointer', font: 'inherit' }}
          onClick={() => navigate(me ? `/` : '/login')}
        >
          <span className="brand-mark">
            <GraduationCap size={18} aria-hidden />
          </span>
          {t('appName')}
        </button>
        <nav className="row-flex" style={{ gap: '8px' }}>
          {me && (
            <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
              {me.name ?? me.email}
            </span>
          )}
          <button
            className="icon-btn"
            aria-label="Switch language"
            onClick={() => {
              const next = getLang() === 'bn' ? 'en' : 'bn'
              setLang(next)
              document.documentElement.setAttribute('lang', next)
              // Pages render t() during render; remount so every string updates.
              navigate(0)
            }}
          >
            <Languages size={18} aria-hidden />
          </button>
          <button className="icon-btn" aria-label="Toggle theme" onClick={() => toggleTheme()}>
            {dark ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
          </button>
          {me && (
            <button className="icon-btn" aria-label={t('logout')} onClick={signOut}>
              <LogOut size={18} aria-hidden />
            </button>
          )}
        </nav>
      </header>

      {children}

      {me?.role === 'student' && (
        <nav className="bottombar" aria-label="Primary">
          {STUDENT_NAV.map(({ to, end, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => (isActive ? 'bnav-item active' : 'bnav-item')}
            >
              <Icon size={22} aria-hidden />
              <span>{t(label)}</span>
              <span className="bnav-dot" aria-hidden />
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  )
}
