import { useCallback, useEffect, useState } from 'react'
import { get, post } from '../api'
import { friendlyError } from '../errors'
import { t } from '../i18n'
import type { StudentBrief, StudentProgress } from '../types'

export default function ParentDashboard() {
  const [children, setChildren] = useState<StudentBrief[]>([])
  const [code, setCode] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<number | null>(null)
  const [progress, setProgress] = useState<StudentProgress | null>(null)

  const loadChildren = useCallback(() => {
    get<StudentBrief[]>('/parents/me/children')
      .then(setChildren)
      .catch((err: unknown) => setError(friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ?? t('errorGeneric')))
  }, [])

  useEffect(() => {
    loadChildren()
  }, [loadChildren])

  useEffect(() => {
    if (selected === null) {
      setProgress(null)
      return
    }
    get<StudentProgress>(`/parents/me/children/${selected}/progress`)
      .then(setProgress)
      .catch((err: unknown) => setError(friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ?? t('errorGeneric')))
  }, [selected])

  async function link(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      // C17: single-use invite code issued by the child — no bare IDs.
      await post('/parents/link/invite', { code: code.trim().toUpperCase() })
      setMessage(t('myChildren') + ' ✓')
      setCode('')
      loadChildren()
    } catch (err) {
      setError(friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ?? t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <h1 className="page-title">{t('parentDashboard')}</h1>

      <div className="card">
        <h2>{t('linkChild')}</h2>
        <p className="muted">
          সন্তানের অ্যাকাউন্টে লগইন করে “{t('account')}” → “{t('parentInviteTitle')}” কোড তৈরি করুন।
        </p>
        <form onSubmit={link} className="grid-2">
          <div>
            <label htmlFor="icode">{t('inviteCodeLabel')}</label>
            <input
              id="icode"
              value={code}
              placeholder="BGPT-XXXXXXXX"
              required
              minLength={8}
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
          <div style={{ alignSelf: 'end' }}>
            <button className="primary" type="submit" disabled={busy}>
              {busy ? <span className="spinner" aria-hidden /> : t('redeem')}
            </button>
          </div>
        </form>
        {message && <p className="ok" role="status">{message}</p>}
        {error && <p className="error" role="alert">{error}</p>}
      </div>

      <div className="card">
        <h2>{t('myChildren')}</h2>
        {children.length === 0 ? (
          <p className="muted">—</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">{t('name')}</th>
                  <th scope="col">{t('className')}</th>
                  <th scope="col">{t('avgScore')}</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {children.map((c) => (
                  <tr key={c.student_id}>
                    <td>{c.student_id}</td>
                    <td>{c.name}</td>
                    <td>{c.class_level}</td>
                    <td>{c.avg_score_pct === null ? '—' : `${c.avg_score_pct}%`}</td>
                    <td>
                      <button className="small secondary" onClick={() => setSelected(c.student_id)}>
                        {t('progressTitle')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected !== null && progress && (
        <div className="card">
          <h2>
            {t('progressTitle')} — {progress.student.name}
          </h2>
          <div className="stat-row">
            <div className="stat">
              <div className="num">{progress.attempts_graded}</div>
              <div className="lbl">{t('gradedQuizzes')}</div>
            </div>
            <div className="stat">
              <div className="num">{progress.avg_score_pct ?? '—'}%</div>
              <div className="lbl">{t('avgScore')}</div>
            </div>
          </div>
          {progress.by_chapter.length > 0 && (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">{t('chapter')}</th>
                    <th scope="col">{t('asked')}</th>
                    <th scope="col">{t('correct')}</th>
                    <th scope="col">{t('accuracy')}</th>
                  </tr>
                </thead>
                <tbody>
                  {progress.by_chapter.map((c) => (
                    <tr key={c.chapter}>
                      <td>{c.chapter}</td>
                      <td>{c.asked}</td>
                      <td>{c.correct}</td>
                      <td>
                        {c.accuracy}%
                        {c.accuracy < 60 && <span className="badge weak"> {t('weak')}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  )
}
