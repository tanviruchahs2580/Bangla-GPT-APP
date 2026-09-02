import { useCallback, useEffect, useState } from 'react'
import { get, post } from '../api'
import { t } from '../i18n'
import type { ClassAnalytics, StudentBrief } from '../types'

export default function TeacherDashboard() {
  const [classLevel, setClassLevel] = useState(6)
  const [roster, setRoster] = useState<StudentBrief[]>([])
  const [analytics, setAnalytics] = useState<ClassAnalytics | null>(null)
  const [error, setError] = useState<string | null>(null)

  // C16: assign a quiz to a specific student straight from the roster.
  const [assignTo, setAssignTo] = useState<number | null>(null)
  const [assignSubject, setAssignSubject] = useState('science')
  const [assignCount, setAssignCount] = useState(5)
  const [assignBusy, setAssignBusy] = useState(false)
  const [assignMsg, setAssignMsg] = useState<string | null>(null)

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

  async function assignQuiz(e: React.FormEvent) {
    e.preventDefault()
    if (assignTo === null || assignBusy) return
    setAssignBusy(true)
    setAssignMsg(null)
    try {
      const started = await post<{ attempt_id: number }>('/quizzes', {
        student_id: assignTo,
        class_level: classLevel,
        subject: assignSubject,
        num_questions: assignCount,
      })
      setAssignMsg(t('assigned', { id: started.attempt_id }))
    } catch (err) {
      setAssignMsg(err instanceof Error ? err.message : t('errorGeneric'))
    } finally {
      setAssignBusy(false)
    }
  }

  return (
    <>
      <h1 className="page-title">{t('teacherDashboard')}</h1>
      <div className="card">
        <label htmlFor="cls">{t('className').replace(/\s*\(.*\)/, '')}</label>
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
        {error && <p className="error" role="alert">{error}</p>}
      </div>

      {analytics && (
        <div className="stat-row">
          <div className="stat">
            <div className="num">{analytics.students}</div>
            <div className="lbl">{t('students')}</div>
          </div>
          <div className="stat">
            <div className="num">{analytics.chapters.length}</div>
            <div className="lbl">{t('chapter')}</div>
          </div>
          <div className="stat">
            <div className="num">{analytics.weak_chapters.length}</div>
            <div className="lbl">{t('weakChapters')}</div>
          </div>
        </div>
      )}

      <div className="card">
        <h2>{t('classStudents')}</h2>
        {roster.length === 0 ? (
          <p className="muted">{t('noStudents')}</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">{t('name')}</th>
                  <th scope="col">{t('className').replace(/\s*\(.*\)/, '')}</th>
                  <th scope="col">{t('quizTitle')}</th>
                  <th scope="col">{t('avgScore')}</th>
                  <th scope="col"></th>
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
                    <td>
                      <button
                        className={`small secondary${assignTo === s.student_id ? ' on-up' : ''}`}
                        onClick={() => setAssignTo(s.student_id)}
                      >
                        {t('assignQuiz')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {assignTo !== null && (
        <div className="card">
          <h3>
            {t('assignQuiz')} — #{assignTo}
          </h3>
          <form onSubmit={assignQuiz} className="grid-2">
            <div>
              <label htmlFor="asubj">{t('subject')}</label>
              <select id="asubj" value={assignSubject} onChange={(e) => setAssignSubject(e.target.value)}>
                <option value="science">বিজ্ঞান</option>
                <option value="math">গণিত</option>
                <option value="bangla">বাংলা</option>
              </select>
              <label htmlFor="acount">{t('questionCount')}</label>
              <input
                id="acount"
                type="number"
                min={1}
                max={10}
                value={assignCount}
                onChange={(e) => setAssignCount(Number(e.target.value))}
              />
            </div>
            <div style={{ alignSelf: 'end' }}>
              <button className="primary" type="submit" disabled={assignBusy}>
                {assignBusy ? <span className="spinner" aria-hidden /> : t('assignQuiz')}
              </button>
              {assignMsg && (
                <p className={assignMsg.includes('#') ? 'ok' : 'error'} role="status">
                  {assignMsg}
                </p>
              )}
            </div>
          </form>
        </div>
      )}

      {analytics && analytics.chapters.length > 0 && (
        <div className="card">
          <h2>
            {t('accuracy')} ({t('className').replace(/\s*\(.*\)/, '')} {analytics.class_level})
          </h2>
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
                {analytics.chapters.map((c) => (
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
        </div>
      )}
    </>
  )
}
