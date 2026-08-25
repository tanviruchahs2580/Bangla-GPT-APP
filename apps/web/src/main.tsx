import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './styles.css'
import { fetchMe, getToken, logout, type MeResponse } from './api'
import AdminDashboard from './pages/AdminDashboard'
import ForgotResetPage from './pages/ForgotResetPage'
import LegalPage from './pages/LegalPage'
import LoginPage from './pages/LoginPage'
import ParentDashboard from './pages/ParentDashboard'
import RegisterPage from './pages/RegisterPage'
import StudentDashboard from './pages/StudentDashboard'
import TeacherDashboard from './pages/TeacherDashboard'

const ROLE_HOME: Record<string, string> = {
  student: '/student',
  teacher: '/teacher',
  parent: '/parent',
  admin: '/admin',
}

function Header({ me }: { me: MeResponse | null }) {
  return (
    <header className="topbar">
      <span className="brand">বাংলা GPT টিউটর</span>
      <nav>
        {me ? (
          <>
            <span className="who">
              {me.name ?? me.email} · {me.role}
            </span>
            <button
              onClick={() => {
                logout()
                window.location.href = '/login'
              }}
            >
              লগআউট
            </button>
          </>
        ) : (
          <a href="/login">লগইন</a>
        )}
      </nav>
    </header>
  )
}

function RequireAuth({ me, role, children }: { me: MeResponse | null; role?: string; children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />
  if (me === null) return <div className="container">লোড হচ্ছে…</div>
  if (role && me.role !== role) return <Navigate to={ROLE_HOME[me.role] ?? '/login'} replace />
  return <>{children}</>
}

function App() {
  const [me, setMe] = useState<MeResponse | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    fetchMe().then((result) => {
      setMe(result)
      setLoaded(true)
    })
  }, [])

  if (!loaded) return <div className="container">লোড হচ্ছে…</div>

  const home = me ? ROLE_HOME[me.role] ?? '/login' : '/login'

  return (
    <BrowserRouter>
      <Header me={me} />
      <main className="container">
        <Routes>
          <Route path="/" element={<Navigate to={home} replace />} />
          <Route path="/login" element={me ? <Navigate to={home} replace /> : <LoginPage onLogin={setMe} />} />
          <Route
            path="/register"
            element={me ? <Navigate to={home} replace /> : <RegisterPage onRegister={setMe} />}
          />
          <Route path="/forgot" element={<ForgotResetPage />} />
          <Route path="/privacy" element={<LegalPage kind="privacy" />} />
          <Route path="/terms" element={<LegalPage kind="terms" />} />
          <Route
            path="/student"
            element={
              <RequireAuth me={me} role="student">
                <StudentDashboard me={me!} />
              </RequireAuth>
            }
          />
          <Route
            path="/teacher"
            element={
              <RequireAuth me={me} role="teacher">
                <TeacherDashboard />
              </RequireAuth>
            }
          />
          <Route
            path="/parent"
            element={
              <RequireAuth me={me} role="parent">
                <ParentDashboard />
              </RequireAuth>
            }
          />
          <Route
            path="/admin"
            element={
              <RequireAuth me={me} role="admin">
                <AdminDashboard />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
