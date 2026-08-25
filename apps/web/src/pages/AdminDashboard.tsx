import { useCallback, useEffect, useState } from 'react'
import { get, patch } from '../api'
import type { AdminOverview, UserPublic } from '../types'

const ROLES = ['student', 'teacher', 'parent', 'admin'] as const

export default function AdminDashboard() {
  const [users, setUsers] = useState<UserPublic[]>([])
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setError(null)
    Promise.all([get<UserPublic[]>('/admin/users'), get<AdminOverview>('/admin/analytics/overview')])
      .then(([u, o]) => {
        setUsers(u)
        setOverview(o)
      })
      .catch((err: Error) => setError(err.message))
  }, [])

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
      setError(err instanceof Error ? err.message : 'ভূমিকা পরিবর্তন ব্যর্থ')
    }
  }

  return (
    <>
      <div className="card">
        <h2>অ্যাডমিন ড্যাশবোর্ড</h2>
        {error && <p className="error">{error}</p>}
        {overview && (
          <div className="stat-row">
            <div className="stat">
              <div className="num">{overview.users_total}</div>
              <div className="lbl">মোট ব্যবহারকারী</div>
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
              <div className="lbl">গ্রেডেড কুইজ</div>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h2>ব্যবহারকারী ব্যবস্থাপনা</h2>
        <table>
          <thead>
            <tr>
              <th>আইডি</th>
              <th>ইমেইল</th>
              <th>ভূমিকা</th>
              <th>যোগদান</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.id}</td>
                <td>{u.email}</td>
                <td>
                  <select value={u.role} onChange={(e) => changeRole(u, e.target.value)}>
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </td>
                <td>{new Date(u.created_at).toLocaleDateString('bn-BD')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
