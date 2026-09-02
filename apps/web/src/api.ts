const API_BASE: string = import.meta.env.VITE_API_BASE ?? '/api'

/** Absolute API base for direct navigation links (downloads etc.). */
export const apiBase = API_BASE

export class ApiError extends Error {
  status: number
  code?: string
  rawDetail: unknown
  constructor(status: number, message: string, code?: string, rawDetail?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.rawDetail = rawDetail
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

/** Called when any API call comes back 401 — lets the app force re-login. */
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn
}

// Auth endpoints where a 401 is part of the API contract (bad credentials / bad code).
// Failing there must surface the inline friendly error, not force a page reload.
const AUTH_401_PATHS = ['/auth/login', '/auth/verify-email', '/auth/reset']

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

function parseDetail(body: unknown): { message: string; code?: string } {
  if (body && typeof body === 'object' && 'detail' in (body as Record<string, unknown>)) {
    const detail = (body as Record<string, unknown>).detail
    if (detail && typeof detail === 'object') {
      const d = detail as Record<string, unknown>
      return { message: String(d.message ?? JSON.stringify(d)), code: d.code ? String(d.code) : undefined }
    }
    return { message: String(detail) }
  }
  if (typeof body === 'string' && body) return { message: body }
  return { message: 'Request failed' }
}

async function parseSse(response: Response, onToken: (text: string) => void): Promise<Record<string, unknown> | null> {
  const reader = response.body?.getReader()
  if (!reader) return null
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = ''
  let done: Record<string, unknown> | null = null
  for (;;) {
    const { value, done: finished } = await reader.read()
    if (finished) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (line.startsWith('event:')) currentEvent = line.slice(6).trim()
      else if (line.startsWith('data:') && currentEvent) {
        try {
          const data = JSON.parse(line.slice(5).trim())
          if (currentEvent === 'token') onToken(String(data.text ?? ''))
          else if (currentEvent === 'done') done = data
          else if (currentEvent === 'error') done = { __error: true, ...data }
        } catch {
          /* ignore malformed frames */
        }
      }
    }
  }
  return done
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  } catch {
    throw new ApiError(0, 'network error', 'network')
  }
  if (res.status === 204) return undefined as T
  if (!res.ok) {
    let parsed: { message: string; code?: string } = { message: res.statusText }
    try {
      parsed = parseDetail(await res.json())
    } catch {
      /* keep statusText */
    }
    if (res.status === 401 && !AUTH_401_PATHS.some((p) => path.startsWith(p))) onUnauthorized?.()
    throw new ApiError(res.status, parsed.message, parsed.code, parsed)
  }  return (await res.json()) as T
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
export const del = (path: string) => api<void>(path, { method: 'DELETE' })

/**
 * POST an SSE endpoint and stream `token` events through `onToken`.
 * Resolves with the parsed `done` event payload.
 */
export async function postStream<T>(
  path: string,
  body: unknown,
  onToken: (text: string) => void,
): Promise<T> {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.headers.get('content-type')?.includes('text/event-stream')) {
    throw new ApiError(res.status, 'stream unavailable', 'llm_unavailable')
  }
  const done = await parseSse(res, onToken)
  if (done && '__error' in done) throw new ApiError(502, 'stream failed', 'llm_unavailable')
  return done as T
}

export interface TokenResponse {
  access_token: string
  token_type?: string
  must_change_password?: boolean
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
  // Validate the session and refresh the authoritative role from the server.
  await fetchMe()
  return decodeRole(res.access_token) ?? 'student'
}

export async function register(input: {
  email: string
  password: string
  name: string
  role: 'student' | 'teacher' | 'parent'
  class_level?: number
  guardian_consent?: boolean
}): Promise<void> {
  await post('/auth/register', input)
}

export async function forgotPassword(email: string): Promise<void> {
  await post('/auth/forgot', { email })
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  const res = await post<TokenResponse>('/auth/reset', { token, new_password: newPassword })
  localStorage.setItem(TOKEN_KEY, res.access_token)
}

export async function verifyEmail(token: string): Promise<void> {
  // V1 contract: token only — the endpoint takes no password fields.
  const res = await post<TokenResponse>('/auth/verify-email', { token })
  localStorage.setItem(TOKEN_KEY, res.access_token)
}

export async function resendVerification(): Promise<void> {
  await post('/auth/resend-verification')
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const res = await post<TokenResponse>('/auth/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
  localStorage.setItem(TOKEN_KEY, res.access_token)
}

/** Student generates a single-use code (BGPT-XXXXXXXX) a parent can redeem to link. */
export async function generateInviteCode(): Promise<{ code: string; expires_in_minutes: number }> {
  return post('/students/me/invite-code')
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

/* -------- Learn catalog (grounded corpus) -------- */
export const getSubjects = (classLevel?: number) =>
  get<import('./types').SubjectOut[]>(
    `/learn/subjects${classLevel ? `?class_level=${classLevel}` : ''}`,
  )

export const getSubjectChapters = (subject: string, classLevel?: number) =>
  get<import('./types').ChapterSummaryOut[]>(
    `/learn/subjects/${encodeURIComponent(subject)}/chapters${
      classLevel ? `?class_level=${classLevel}` : ''
    }`,
  )

export const getChapterContent = (
  subject: string,
  chapter: string,
  classLevel?: number,
) =>
  get<import('./types').ChapterContentOut>(
    `/learn/subjects/${encodeURIComponent(subject)}/chapters/${encodeURIComponent(
      chapter,
    )}${classLevel ? `?class_level=${classLevel}` : ''}`,
  )
