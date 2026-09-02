import { useCallback, useEffect, useState } from 'react'
import { get, patch, post } from '../api'
import { t } from '../i18n'
import type { AdminOverview, AdminUsersPage, UserPublic } from '../types'

const ROLES = ['student', 'teacher', 'parent', 'admin'] as const

export default function AdminDashboard() {
  const [page, setPage] = useState<AdminUsersPage>({ total: 0, items: [] })
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [purgeMsg, setPurgeMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const LIMIT = 20

  const load = useCallback(() => {
    setError(null)
    const params: Record<string, string | number> = { limit: LIMIT, offset }
    if (query.trim()) params.q = query.trim()
    if (roleFilter) params.role = roleFilter
    const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))
    Promise.all([get<AdminUsersPage>(`/admin/users?${qs}`), get<AdminOverview>('/admin/analytics/overview')])
      .then(([u, o]) => {
        setPage(u)
        setOverview(o)
      })
      .catch((err: Error) => setError(err.message))
  }, [offset, query, roleFilter])

  useEffect(() => {
    load()
  }, [load])

  async function changeRole(user: UserPublic, role: string) {
    if (role === user.role) return
    setError(null)
    try {
      await patch(`/admin/users/${user.id}/role`, { role })
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('errorGeneric'))
    }
  }

  async function purge() {
    setPurgeMsg(null)
    try {
      const res = await post<Record<string, number>>('/admin/maintenance/purge')
      setPurgeMsg(`${t('purged')}: ${JSON.stringify(res)}`)
    } catch (err) {
      setPurgeMsg(err instanceof Error ? err.message : t('errorGeneric'))
    }
  }

  return (
    <>
      <h1 className="page-title">{t('adminDashboard')}</h1>

      <div className="card">
        <h2>{t('maintenance')}</h2>
        <button className="secondary" onClick={purge}>{t('purgeExpired')}</button>
        {purgeMsg && <p className="muted" role="status">{purgeMsg}</p>}
      </div>

      <div className="card">
        <h2>{t('adminDashboard')}</h2>
        {error && <p className="error" role="alert">{error}</p>}
        {overview && (
          <div className="stat-row">
            <div className="stat">
              <div className="num">{overview.users_total}</div>
              <div className="lbl">মোট</div>
            </div>
            <div className="stat">
              <div className="num">{overview.students}</div>
              <div className="lbl">শিক্ষার্থী</div>
            </div>
            <div className="stat">
              <div className="num">{overview.teachers}</div>
              <div className="lbl">শিক্ষক</div>
            </div>
            <div className="stat">
              <div className="num">{overview.parents}</div>
              <div className="lbl">অভিভাবক</div>
            </div>
            <div className="stat">
              <div className="num">{overview.quiz_attempts_graded}</div>
              <div className="lbl">কুইজ</div>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h2>{t('searchEmail')}</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            setOffset(0)
            load()
          }}
        >
          <label htmlFor="q">{t('searchEmail')}</label>
          <input id="q" value={query} placeholder={t('searchEmail')} onChange={(e) => setQuery(e.target.value)} />
          <label htmlFor="rfilter">{t('role')}</label>
          <select id="rfilter" value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); setOffset(0) }}>
            <option value="">—</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <button className="primary small" type="submit">{t('send')}</button>
        </form>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">{t('email')}</th>
                <th scope="col">{t('role')}</th>
                <th scope="col"></th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((u) => (
                <tr key={u.id}>
                  <td>{u.id}</td>
                  <td style={{ whiteSpace: 'normal' }}>{u.email}</td>
                  <td>{u.role}</td>
                  <td>
                    <select value={u.role} onChange={(e) => changeRole(u, e.target.value)} aria-label={`${u.email} ${t('role')}`}>
                      {ROLES.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted">
          {page.total} — {offset + 1}–{Math.min(offset + LIMIT, page.total)}
          {' '}
          <button className="small secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>
            ‹
          </button>{' '}
          <button
            className="small secondary"
            disabled={offset + LIMIT >= page.total}
            onClick={() => setOffset(offset + LIMIT)}
          >
            ›
          </button>
        </p>
      </div>
    </>
  )
}
