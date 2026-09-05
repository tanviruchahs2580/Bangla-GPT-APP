import React, { lazy, Suspense } from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, Link } from 'react-router-dom'
import * as Sentry from '@sentry/react'

// S0.6: Sentry — no-op when DSN absent
if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN as string,
    environment: import.meta.env.MODE,
    tracesSampleRate: 0.1,
  })
}
import './styles.css'
import '@fontsource/noto-sans-bengali/400.css'
import '@fontsource/noto-sans-bengali/700.css'
import '@fontsource/hind-siliguri/400.css'
import '@fontsource/hind-siliguri/600.css'
import { getToken } from './api'
import { AuthProvider, ROLE_HOME, useAuth } from './AuthContext'
import { AppShell } from './AppShell'
import { t } from './i18n'

const LoginPage = lazy(() => import('./pages/LoginPage'))
const RegisterPage = lazy(() => import('./pages/RegisterPage'))
const ForgotResetPage = lazy(() => import('./pages/ForgotResetPage'))
const LegalPage = lazy(() => import('./pages/LegalPage'))
const HomePage = lazy(() => import('./pages/student/HomePage'))
const AITutorPage = lazy(() => import('./pages/student/AITutorPage'))
const QuizPage = lazy(() => import('./pages/student/QuizPage'))
const MePage = lazy(() => import('./pages/student/MePage'))
const LearnPage = lazy(() =>
  import('./pages/student/LearnPage').then((m) => ({ default: m.LearnPage })),
)
const LearnChapterPage = lazy(() =>
  import('./pages/student/LearnPage').then((m) => ({ default: m.LearnChapterPage })),
)
const TeacherDashboard = lazy(() => import('./pages/TeacherDashboard'))
const ParentDashboard = lazy(() => import('./pages/ParentDashboard'))
const AdminDashboard = lazy(() => import('./pages/AdminDashboard'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

function RequireAuth({
  role,
  children,
}: {
  role?: string
  children: React.ReactNode
}) {
  const { me, loading } = useAuth()
  if (!getToken()) return <Navigate to="/login" replace />
  if (loading || me === null)
    return (
      <main className="container" aria-live="polite">
        <p className="muted">{t('loading')}</p>
        <div className="skeleton" style={{ width: '60%' }} />
        <div className="skeleton" style={{ width: '40%' }} />
      </main>
    )
  if (role && me.role !== role) return <Navigate to={ROLE_HOME[me.role] ?? '/login'} replace />
  return <AppShell>{children}</AppShell>
}

function Loading() {
  return (
    <main className="container" aria-live="polite">
      <p className="muted">{t('loading')}</p>
      <div className="skeleton" style={{ width: '70%' }} />
      <div className="skeleton" style={{ width: '55%' }} />
      <div className="skeleton" style={{ width: '80%' }} />
    </main>
  )
}

function RoutesSwitch() {
  const { me, loading } = useAuth()
  const home = me ? ROLE_HOME[me.role] ?? '/login' : '/login'
  if (loading) return <Loading />

  return (
    <Routes>
      <Route path="/" element={<Navigate to={home} replace />} />
      <Route path="/login" element={me ? <Navigate to={home} replace /> : <LoginPage />} />
      <Route path="/register" element={me ? <Navigate to={home} replace /> : <RegisterPage />} />
      <Route path="/forgot" element={<ForgotResetPage />} />
      <Route path="/privacy" element={<LegalPage kind="privacy" />} />
      <Route path="/terms" element={<LegalPage kind="terms" />} />

      <Route
        path="/student"
        element={
          <RequireAuth role="student">
            <HomePage />
          </RequireAuth>
        }
      />
      <Route
        path="/student/learn"
        element={
          <RequireAuth role="student">
            <LearnPage />
          </RequireAuth>
        }
      />
      <Route
        path="/student/learn/:subject/:chapter"
        element={
          <RequireAuth role="student">
            <LearnChapterPage />
          </RequireAuth>
        }
      />
      <Route
        path="/student/tutor"
        element={
          <RequireAuth role="student">
            <AITutorPage />
          </RequireAuth>
        }
      />
      <Route
        path="/student/quiz"
        element={
          <RequireAuth role="student">
            <QuizPage />
          </RequireAuth>
        }
      />
      <Route
        path="/student/me"
        element={
          <RequireAuth role="student">
            <MePage />
          </RequireAuth>
        }
      />

      <Route path="/teacher" element={<RequireAuth role="teacher"><TeacherDashboard /></RequireAuth>} />
      <Route path="/parent" element={<RequireAuth role="parent"><ParentDashboard /></RequireAuth>} />
      <Route path="/admin" element={<RequireAuth role="admin"><AdminDashboard /></RequireAuth>} />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading />}>
        <RoutesSwitch />
        <Footer />
      </Suspense>
    </BrowserRouter>
  )
}

function Footer() {
  return (
    <footer className="footer">
      <div>
        <Link to="/privacy">{t('privacy')}</Link> · <Link to="/terms">{t('terms')}</Link>
      </div>
      <div>
        © {new Date().getFullYear()} {t('appName')}
      </div>
    </footer>
  )
}

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="container" role="alert">
          <div className="card">
            <h2>{t('errorGeneric')}</h2>
            <p className="muted">{this.state.error.message}</p>
            <button className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
)

// PWA: register the service worker in production builds only — in dev the
// cache-first strategy would serve stale Vite modules and break HMR.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* offline support is best-effort; never block the app on SW errors */
    })
  })
}
