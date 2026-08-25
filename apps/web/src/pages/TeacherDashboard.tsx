import { useCallback, useEffect, useState } from 'react'
import { get } from '../api'
import type { ClassAnalytics, StudentBrief } from '../types'

export default function TeacherDashboard() {
  const [classLevel, setClassLevel] = useState(6)
  const [roster, setRoster] = useState<StudentBrief[]>([])
  const [analytics, setAnalytics] = useState<ClassAnalytics | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setError(null)
    Promise.all([
      get<StudentBrief[]>(`/teacher/students?class_level=${classLevel}`),
      get<ClassAnalytics>(`/teacher/classes/${classLevel}/analytics`),
    ])
      .then(([r, a]) => {
        setRoster(r)
        setAnalytics(a)
      })
      .catch((err: Error) => setError(err.message))
  }, [classLevel])

  useEffect(() => {
    load()
  }, [load])

  return (
    <>
      <div className="card">
        <h2>শিক্ষক ড্যাশবোর্ড</h2>
        <label htmlFor="cls">শ্রেণি</label>
        <input
          id="cls"
          type="number"
          min={1}
          max={12}
          value={classLevel}
          onChange={(e) => setClassLevel(Number(e.target.value))}
        />
        <button className="primary" onClick={load}>
          রিফ্রেশ
        </button>
        {error && <p className="error">{error}</p>}
      </div>

      {analytics && (
        <div className="stat-row">
          <div className="stat">
            <div className="num">{analytics.students}</div>
            <div className="lbl">শিক্ষার্থী</div>
          </div>
          <div className="stat">
            <div className="num">{analytics.chapters.length}</div>
            <div className="lbl">অধ্যায় রেকর্ড</div>
          </div>
          <div className="stat">
            <div className="num">{analytics.weak_chapters.length}</div>
            <div className="lbl">দুর্বল অধ্যায়</div>
          </div>
        </div>
      )}

      <div className="card">
        <h2>শ্রেণির শিক্ষার্থীবৃন্দ</h2>
        {roster.length === 0 ? (
          <p className="muted">এই শ্রেণিতে কোনো শিক্ষার্থী নেই।</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>আইডি</th>
                <th>নাম</th>
                <th>শ্রেণি</th>
                <th>কুইজ</th>
                <th>গড়</th>
              </tr>
            </thead>
            <tbody>
              {roster.map((s) => (
                <tr key={s.student_id}>
                  <td>{s.student_id}</td>
                  <td>{s.name}</td>
                  <td>{s.class_level}</td>
                  <td>{s.attempts_graded}</td>
                  <td>{s.avg_score_pct === null ? '—' : `${s.avg_score_pct}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {analytics && analytics.chapters.length > 0 && (
        <div className="card">
          <h2>অধ্যায়ভিত্তিক নির্ভুলতা (শ্রেণি {analytics.class_level})</h2>
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
              {analytics.chapters.map((c) => (
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
        </div>
      )}
    </>
  )
}
