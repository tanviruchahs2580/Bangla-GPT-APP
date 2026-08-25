import { useCallback, useEffect, useState } from 'react'
import { del, get, post } from '../api'
import type { MeResponse } from '../api'
import type { AskResponse, QuizResult, QuizStarted, StudentProgress } from '../types'

export default function StudentDashboard({ me }: { me: MeResponse }) {
  const studentId = me.profile_id

  const [question, setQuestion] = useState('')
  const [subject, setSubject] = useState('science')
  const [answer, setAnswer] = useState<AskResponse | null>(null)
  const [askError, setAskError] = useState<string | null>(null)

  const [numQuestions, setNumQuestions] = useState(5)
  const [quiz, setQuiz] = useState<QuizStarted | null>(null)
  const [choices, setChoices] = useState<number[]>([])
  const [result, setResult] = useState<QuizResult | null>(null)
  const [quizError, setQuizError] = useState<string | null>(null)

  const [progress, setProgress] = useState<StudentProgress | null>(null)
  const [progressError, setProgressError] = useState<string | null>(null)

  const loadProgress = useCallback(() => {
    if (studentId === null) return
    get<StudentProgress>(`/students/${studentId}/progress`)
      .then(setProgress)
      .catch((err: Error) => setProgressError(err.message))
  }, [studentId])

  useEffect(() => {
    loadProgress()
  }, [loadProgress])

  async function ask(e: React.FormEvent) {
    e.preventDefault()
    setAskError(null)
    setAnswer(null)
    try {
      setAnswer(
        await post<AskResponse>('/tutor/ask', {
          question,
          class_level: me.class_level ?? 6,
          subject,
        }),
      )
    } catch (err) {
      setAskError(err instanceof Error ? err.message : 'উত্তর পাওয়া যায়নি')
    }
  }

  async function startQuiz() {
    if (studentId === null) return
    setQuizError(null)
    setResult(null)
    try {
      const started = await post<QuizStarted>('/quizzes', {
        student_id: studentId,
        class_level: me.class_level ?? undefined,
        subject,
        num_questions: numQuestions,
      })
      setQuiz(started)
      setChoices(Array(started.questions.length).fill(0))
    } catch (err) {
      setQuizError(err instanceof Error ? err.message : 'কুইজ শুরু করা যায়নি')
    }
  }

  async function submitQuiz() {
    if (!quiz) return
    setQuizError(null)
    try {
      const res = await post<QuizResult>(`/quizzes/${quiz.attempt_id}/submit`, {
        answers: choices,
      })
      setResult(res)
      setQuiz(null)
      loadProgress()
    } catch (err) {
      setQuizError(err instanceof Error ? err.message : 'জমা দেওয়া যায়নি')
    }
  }

  async function deleteAccount() {
    if (!confirm('আপনার সব ডেটা মুছে ফেলা হবে। নিশ্চিত?')) return
    await del('/users/me')
    window.location.href = '/login'
  }

  return (
    <>
      <div className="card">
        <h2>
          টিউটর — {me.name} (শ্রেণি {me.class_level})
        </h2>
        <form onSubmit={ask}>
          <div className="grid-2">
            <div>
              <label htmlFor="q">প্রশ্ন</label>
              <textarea id="q" value={question} required minLength={3} onChange={(e) => setQuestion(e.target.value)} />
            </div>
            <div>
              <label htmlFor="subj">বিষয়</label>
              <select id="subj" value={subject} onChange={(e) => setSubject(e.target.value)}>
                <option value="science">বিজ্ঞান</option>
                <option value="math">গণিত</option>
                <option value="bangla">বাংলা</option>
              </select>
            </div>
          </div>
          <button className="primary" type="submit">
            প্রশ্ন করুন
          </button>
        </form>
        {askError && <p className="error">{askError}</p>}
        {answer && (
          <div style={{ marginTop: 12 }}>
            <span className={`badge ${answer.grounded ? 'grounded' : 'refused'}`}>
              {answer.grounded ? 'পাঠ্যবই-সমর্থিত' : 'প্রমাণ নেই'}
            </span>
            <p>{answer.answer}</p>
            {answer.sources.length > 0 && (
              <ul className="sources">
                {answer.sources.map((s, i) => (
                  <li key={i}>
                    📘 {s.book} · {s.chapter}
                    {s.section ? ` · ${s.section}` : ''}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h2>কুইজ</h2>
        {!quiz && !result && (
          <>
            <label htmlFor="nq">প্রশ্ন সংখ্যা</label>
            <input
              id="nq"
              type="number"
              min={1}
              max={10}
              value={numQuestions}
              onChange={(e) => setNumQuestions(Number(e.target.value))}
            />
            <button className="primary" onClick={startQuiz}>
              কুইজ শুরু করুন
            </button>
          </>
        )}
        {quiz && (
          <>
            {quiz.questions.map((qq, qi) => (
              <div key={qq.id} style={{ marginBottom: 16 }}>
                <h3>
                  {qi + 1}. {qq.question_text}
                </h3>
                {qq.options.map((opt, oi) => (
                  <label key={oi} style={{ display: 'block' }}>
                    <input
                      type="radio"
                      name={qq.id}
                      checked={choices[qi] === oi}
                      onChange={() =>
                        setChoices(choices.map((c, i) => (i === qi ? oi : c)))
                      }
                      style={{ width: 'auto', marginRight: 8 }}
                    />
                    {opt}
                  </label>
                ))}
              </div>
            ))}
            <button className="primary" onClick={submitQuiz}>
              জমা দিন
            </button>
          </>
        )}
        {result && (
          <>
            <p className="ok">
              স্কোর: {result.correct}/{result.total} ({result.score_pct}%)
            </p>
            {result.review.map((r, i) => (
              <div key={i} className="review-item">
                <strong>{r.question_text}</strong>
                <p className={r.is_correct ? 'ok' : 'error'}>
                  আপনার উত্তর: {r.options[r.chosen]} —{' '}
                  {r.is_correct ? 'সঠিক ✓' : `ভুল (সঠিক: ${r.options[r.correct_index]})`}
                </p>
                <span className="muted">অধ্যায়: {r.chapter}</span>
              </div>
            ))}
          </>
        )}
        {quizError && <p className="error">{quizError}</p>}
      </div>

      <div className="card">
        <h2>আমার অগ্রগতি</h2>
        {progressError && <p className="error">{progressError}</p>}
        {progress && (
          <>
            <div className="stat-row">
              <div className="stat">
                <div className="num">{progress.attempts_graded}</div>
                <div className="lbl">গ্রেড করা কুইজ</div>
              </div>
              <div className="stat">
                <div className="num">{progress.avg_score_pct ?? '—'}%</div>
                <div className="lbl">গড় স্কোর</div>
              </div>
              <div className="stat">
                <div className="num">{progress.weak_chapters.length}</div>
                <div className="lbl">দুর্বল অধ্যায়</div>
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
          </>
        )}
      </div>

      <div className="card">
        <h3>অ্যাকাউন্ট</h3>
        <button onClick={deleteAccount}>আমার অ্যাকাউন্ট মুছুন</button>
        <span className="muted" style={{ marginLeft: 8 }}>
          আপনার সমস্ত প্রোফাইল ও কুইজ ডেটা স্থায়ীভাবে মুছে যাবে।
        </span>
      </div>
    </>
  )
}
