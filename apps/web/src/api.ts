const API_BASE: string = import.meta.env.VITE_API_BASE ?? '/api'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export interface MeResponse {
  user_id: number
  email: string
  role: 'student' | 'teacher' | 'parent' | 'admin'
  profile_id: number | null
  name: string | null
  class_level: number | null
}

const TOKEN_KEY = 'bgpt_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body !== undefined) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (res.status === 204) return undefined as T
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: unknown }
      detail =
        typeof body.detail === 'string'
          ? body.detail
          : body.detail !== undefined
            ? JSON.stringify(body.detail)
            : detail
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
export const del = (path: string) => api<void>(path, { method: 'DELETE' })

export interface TokenResponse {
  access_token: string
}

function decodeRole(token: string): string | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/')))
    return typeof payload.role === 'string' ? payload.role : null
  } catch {
    return null
  }
}

export async function login(email: string, password: string): Promise<string> {
  const res = await post<TokenResponse>('/auth/login', { email, password })
  localStorage.setItem(TOKEN_KEY, res.access_token)
  // Validate the session and refresh authoritative role from the server.
  await fetchMe()
  return decodeRole(res.access_token) ?? 'student'
}

export async function register(input: {
  email: string
  password: string
  name: string
  role: 'student' | 'teacher' | 'parent'
  class_level?: number
}): Promise<void> {
  await post('/auth/register', input)
}

let meCache: MeResponse | null = null

export async function fetchMe(): Promise<MeResponse | null> {
  if (!getToken()) {
    meCache = null
    return null
  }
  try {
    meCache = await get<MeResponse>('/users/me')
    return meCache
  } catch {
    logout()
    return null
  }
}

export function cachedMe(): MeResponse | null {
  return meCache
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY)
  meCache = null
}
