import { useCallback, useEffect, useState } from 'react'
import { get, post } from '../api'
import type { StudentBrief, StudentProgress } from '../types'

export default function ParentDashboard() {
  const [children, setChildren] = useState<StudentBrief[]>([])
  const [linkId, setLinkId] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [progress, setProgress] = useState<StudentProgress | null>(null)

  const loadChildren = useCallback(() => {
    get<StudentBrief[]>('/parents/me/children')
      .then(setChildren)
      .catch((err: Error) => setError(err.message))
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
      .catch((err: Error) => setError(err.message))
  }, [selected])

  async function link(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setMessage(null)
    try {
      await post('/parents/link', { student_id: Number(linkId) })
      setMessage(`শিক্ষার্থী #${linkId} সংযুক্ত হয়েছে`)
      setLinkId('')
      loadChildren()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'সংযোগ ব্যর্থ হয়েছে')
    }
  }

  return (
    <>
      <div className="card">
        <h2>অভিভাবক ড্যাশবোর্ড</h2>
        <form onSubmit={link} className="grid-2">
          <div>
            <label htmlFor="sid">শিক্ষার্থীর আইডি</label>
            <input
              id="sid"
              type="number"
              min={1}
              value={linkId}
              required
              onChange={(e) => setLinkId(e.target.value)}
            />
          </div>
          <div style={{ alignSelf: 'end' }}>
            <button className="primary" type="submit">
              সন্তান সংযুক্ত করুন
            </button>
          </div>
        </form>
        {message && <p className="ok">{message}</p>}
        {error && <p className="error">{error}</p>}
      </div>

      <div className="card">
        <h2>আমার সন্তানেরা</h2>
        {children.length === 0 ? (
          <p className="muted">কোনো শিক্ষার্থী সংযুক্ত নেই।</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>আইডি</th>
                <th>নাম</th>
                <th>শ্রেণি</th>
                <th>গড়</th>
                <th></th>
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
                    <button className="small" onClick={() => setSelected(c.student_id)}>
                      অগ্রগতি
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected !== null && progress && (
        <div className="card">
          <h2>
            অগ্রগতি — {progress.student.name} (শ্রেণি {progress.student.class_level})
          </h2>
          <div className="stat-row">
            <div className="stat">
              <div className="num">{progress.attempts_graded}</div>
              <div className="lbl">কুইজ</div>
            </div>
            <div className="stat">
              <div className="num">{progress.avg_score_pct ?? '—'}%</div>
              <div className="lbl">গড় স্কোর</div>
            </div>
          </div>
          {progress.by_chapter.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>অধ্যায়</th>
                  <th>প্রশ্ন</th>
                  <th>সঠিক</th>
                  <th>নির্ভুলতা</th>
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
                      {c.accuracy < 60 && <span className="badge weak">দুর্বল</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  )
}
