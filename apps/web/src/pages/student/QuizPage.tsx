import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Check, ClipboardCheck, RefreshCcw } from 'lucide-react'
import { get, post } from '../../api'
import type { QuizResult, QuizStarted, StudentProgress } from '../../types'
import { useAuth } from '../../AuthContext'
import { Badge, Button, Card, ProgressRing, Stat } from '../../components/ui'
import { friendlyError } from '../../errors'
import { t } from '../../i18n'
import { cn } from '../../lib/cn'

const SUBJECTS = [
  { value: 'science', label: 'বিজ্ঞান' },
  { value: 'mathematics', label: 'গণিত' },
  { value: 'bangla', label: 'বাংলা' },
]

export default function QuizPage() {
  const { me } = useAuth()
  const [number, setNumber] = useState<string>('5')
  const [started, setStarted] = useState<QuizStarted | null>(null)
  const [answers, setAnswers] = useState<Record<number, number>>({})
  const [current, setCurrent] = useState(0)
  const [result, setResult] = useState<QuizResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: progress } = useQuery({
    queryKey: ['progress', me?.profile_id],
    queryFn: () => get<StudentProgress>(`/students/${me!.profile_id}/progress`),
    enabled: !!me?.profile_id && me.role === 'student',
  })

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await post<QuizStarted>('/quizzes', {
        student_id: me?.profile_id,
        class_level: me?.class_level ?? 6,
        subject: SUBJECTS[0].value,
        num_questions: Math.min(20, Math.max(1, Number(number) || 5)),
      })
      setStarted(res)
      setAnswers({})
      setCurrent(0)
      setResult(null)
    } catch (e) {
      setError(friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ?? t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  const submit = async () => {
    setBusy(true)
    try {
      const res = await post<QuizResult>(`/quizzes/${started!.attempt_id}/submit`, {
        answers: started!.questions.map((_, i) => answers[i] ?? -1),
      })
      setResult(res)
      setStarted(null)
    } catch (e) {
      setError(friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ?? t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  // ----- result screen -----
  if (result) {
    return (
      <main className="shell-main">
        <section className="section-head">
          <h2>{t('yourQuizResult')}</h2>
        </section>
        <Card>
          <div className="row-flex" style={{ justifyContent: 'center', flexDirection: 'column', textAlign: 'center' }}>
            <ProgressRing value={result.score_pct} size={120} label={<strong>{Math.round(result.score_pct)}%</strong>} />
            <div className="stat-value" style={{ marginTop: 'var(--space-3)' }}>
              {t('correctOutOf', { correct: result.correct, total: result.total })}
            </div>
          </div>
          <div className="stack" style={{ marginTop: 'var(--space-5)' }}>
            {result.review.map((r, i) => (
              <Card key={i} className="row" style={{ padding: 'var(--space-3)' }}>
                <span className="quick-icon" style={r.is_correct ? { background: 'var(--ok-soft)', color: 'var(--ok)' } : { background: 'var(--danger-soft)', color: 'var(--danger)' }}>
                  {r.is_correct ? <Check size={18} aria-hidden /> : <ClipboardCheck size={18} aria-hidden />}
                </span>
                <div className="row-main">
                  <div className="row-title">{r.question_text}</div>
                  <div className="row-sub">
                    {t('chapter')}: {r.chapter} —{' '}
                    {r.options[r.correct_index] ?? ''}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </Card>
        <div style={{ marginTop: 'var(--space-4)' }}>
          <Button variant="primary" block onClick={() => { setResult(null); start() }}>
            <RefreshCcw size={18} aria-hidden /> {t('startQuiz')}
          </Button>
        </div>
      </main>
    )
  }

  // ----- in-progress quiz -----
  if (started) {
    const q = started.questions[current]
    const chosen = answers[current]
    const answeredCount = Object.keys(answers).length
    return (
      <main className="shell-main">
        <section className="section-head">
          <h2>{t('quiz')}</h2>
          <Badge>
            {current + 1}/{started.questions.length}
          </Badge>
        </section>
        <Card>
          <div className="row-flex" style={{ marginBottom: 'var(--space-3)' }}>
            <ProgressRing value={(answeredCount / started.questions.length) * 100} size={64} label={<strong>{answeredCount}/{started.questions.length}</strong>} />
            <div className="row-main">
              <div className="row-title" style={{ fontSize: 'var(--fs-lg)' }}>{q.question_text}</div>
              <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{t('chooseAnswers')}</div>
            </div>
          </div>
          <div className="stack">
            {q.options.map((opt, oi) => (
              <button
                key={oi}
                className={cn('btn btn-ghost', chosen === oi && 'btn-soft')}
                style={{ textAlign: 'left', justifyContent: 'flex-start' }}
                onClick={() => setAnswers((a) => ({ ...a, [current]: oi }))}
              >
                {opt}
              </button>
            ))}
          </div>
          <div className="row-flex" style={{ justifyContent: 'space-between', marginTop: 'var(--space-5)' }}>
            <Button variant="ghost" size="sm" disabled={current === 0} onClick={() => setCurrent((c) => c - 1)}>
              <ArrowLeft size={16} aria-hidden /> {t('previousQuestion')}
            </Button>
            {current < started.questions.length - 1 ? (
              <Button variant="primary" size="sm" onClick={() => setCurrent((c) => c + 1)}>
                {t('nextQuestion')} <ArrowRight size={16} aria-hidden />
              </Button>
            ) : (
              <Button variant="teal" size="sm" onClick={submit} disabled={busy}>
                {t('finishQuiz')}
              </Button>
            )}
          </div>
          {error && <p className="error" style={{ marginTop: 'var(--space-3)' }}>{error}</p>}
        </Card>
      </main>
    )
  }

  // ----- start screen -----
  const avg = progress?.avg_score_pct
  return (
    <main className="shell-main">
      <section className="section-head">
        <h2>{t('quiz')}</h2>
      </section>
      <Card>
        <div className="card-title">{t('startQuiz')}</div>
        <div className="field">
          <label htmlFor="qcount">{t('questionCount')}</label>
          <select id="qcount" className="select" value={number} onChange={(e) => setNumber(e.target.value)}>
            {[3, 5, 10, 15].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>{t('subject')}</label>
          <select className="select" defaultValue={SUBJECTS[0].value}>
            {SUBJECTS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>
        {progress && progress.attempts_graded > 0 && (
          <div className="stat-grid" style={{ marginTop: 'var(--space-3)' }}>
            <Stat value={Math.round(avg ?? 0) + '%'} label={t('avgScore')} />
            <Stat value={progress.attempts_graded} label={t('gradedQuizzes')} />
          </div>
        )}
        {error && <p className="error">{error}</p>}
        <Button variant="primary" block onClick={start} disabled={busy || !me?.profile_id}>
          {t('startQuiz')}
        </Button>
        {!me?.profile_id && <p className="muted" style={{ fontSize: 'var(--fs-sm)', marginTop: 'var(--space-2)' }}>{t('notStarted')}</p>}
      </Card>
    </main>
  )
}
