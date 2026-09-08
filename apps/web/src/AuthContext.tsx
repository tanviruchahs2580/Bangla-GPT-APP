import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { fetchMe, logout, setUnauthorizedHandler, type MeResponse } from './api'

interface AuthState {
  me: MeResponse | null
  loading: boolean
  setMe: (me: MeResponse | null) => void
  signOut: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchMe().then((result) => {
      setMe(result)
      setLoading(false)
    })
    setUnauthorizedHandler(() => {
      logout()
      window.location.href = '/login'
    })
    return () => setUnauthorizedHandler(() => {})
  }, [])

  const signOut = () => {
    logout()
    setMe(null)
    window.location.href = '/login'
  }

  return (
    <AuthContext.Provider value={{ me, loading, setMe, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export const ROLE_HOME: Record<string, string> = {
  student: '/student',
  teacher: '/teacher',
  parent: '/parent',
  admin: '/admin',
  school_admin: '/school',
}
