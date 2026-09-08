import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Check, ClipboardCheck, RefreshCcw, Repeat2 } from 'lucide-react'
import { get, post } from '../../api'
import type {
  AssignmentMine,
  QuizResult,
  QuizStarted,
  ReteachCard,
  RevisionDue,
  RevisionItemOut,
  ShortTestMine,
  StudentProgress,
} from '../../types'
import { buildExplainPayload, LAST_RESULT_KEY } from '../../lib/quizExplain'
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

// S4.5: KG gap -> grounded re-teach card (textbook excerpt, never AI text).
function ReteachCards({ cards }: { cards: ReteachCard[] }) {
  if (cards.length === 0) return null
  return (
    <Card className="reteach-card">
      <div className="card-title">{t('reteachTitle')}</div>
      <p className="muted" style={{ margin: '0 0 var(--space-2)', fontSize: 'var(--fs-sm)' }}>
        {t('reteachHint')}
      </p>
      <div className="stack">
        {cards.map((c, i) => (
          <div key={i} className="reteach-item">
            <div className="row-title">{t('reteachChain', { concept: c.concept, prereq: c.prereq })}</div>
            <p className="reteach-excerpt">{c.excerpt}</p>
          </div>
        ))}
      </div>
    </Card>
  )
}

export default function QuizPage() {
  const { me } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [number, setNumber] = useState<string>('5')
  // S1.4: the tutor's quiz chip preselects the subject via ?subject=.
  const [subject, setSubject] = useState<string>(searchParams.get('subject') ?? SUBJECTS[0].value)
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

  // S1.10: spaced-revision tab (SM-2-lite queue) with due badge.
  const [tab, setTab] = useState<'quiz' | 'revision' | 'shorttest' | 'assigned'>('quiz')
  const { data: due, refetch: refetchDue } = useQuery({
    queryKey: ['revision-due'],
    queryFn: () => get<RevisionDue>('/revision/due'),
    enabled: me?.role === 'student',
  })
  // S2.5: teacher-assigned short tests (soft time window).
  const { data: stMine } = useQuery({
    queryKey: ['shorttests-mine'],
    queryFn: () => get<ShortTestMine[]>('/shorttests/mine'),
    enabled: me?.role === 'student',
  })
  const openShortTest = (st: ShortTestMine) => {
    if (st.attempt_id === null) return
    setStarted({
      attempt_id: st.attempt_id,
      questions: st.questions,
      requested: st.num_questions,
    })
    setAnswers({})
    setCurrent(0)
    setResult(null)
  }
  // S2.8: teacher bulk-assigned quizzes (shared question set + due date).
  const { data: asMine } = useQuery({
    queryKey: ['assignments-mine'],
    queryFn: () => get<AssignmentMine[]>('/assignments/mine'),
    enabled: me?.role === 'student',
  })
  const openAssigned = (a: AssignmentMine) => {
    if (a.done) return
    setStarted({ attempt_id: a.attempt_id, questions: a.questions, requested: a.questions.length })
    setAnswers({})
    setCurrent(0)
    setResult(null)
  }
  const [revisionBusy, setRevisionBusy] = useState(false)

  const answerRevision = async (item: RevisionItemOut, chosen: number) => {
    setRevisionBusy(true)
    setError(null)
    try {
      await post(`/revision/${item.id}/review`, { chosen })
      await refetchDue()
    } catch (e) {
      setError(friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ?? t('errorGeneric'))
    } finally {
      setRevisionBusy(false)
    }
  }

  // S1.7: restore the last graded result when returning from the tutor explain flow.
  useEffect(() => {
    if (searchParams.get('result') !== '1') return
    try {
      const raw = sessionStorage.getItem(LAST_RESULT_KEY)
      if (raw) setResult(JSON.parse(raw) as QuizResult)
    } catch {
      /* stale cache — start screen is fine */
    }
  }, [searchParams])

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await post<QuizStarted>('/quizzes', {
        student_id: me?.profile_id,
        class_level: me?.class_level ?? 6,
        subject: subject,
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
      // S1.7: keep the result for the tutor explain back-link (?result=1).
      try {
        sessionStorage.setItem(LAST_RESULT_KEY, JSON.stringify(res))
      } catch {
        /* storage may be unavailable in low-data/incognito mode */
      }
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
                  {!r.is_correct && (
                    // S1.7: wrong item → explain loop with full quiz context.
                    <Button
                      variant="ghost"
                      size="sm"
                      style={{ marginTop: 'var(--space-2)' }}
                      onClick={() =>
                        navigate('/student/tutor', {
                          state: { explain: buildExplainPayload(r), backToResult: true },
                        })
                      }
                    >
                      {t('explainThis')}
                    </Button>
                  )}
                </div>
              </Card>
            ))}
          </div>
        </Card>
        {result.reteach && result.reteach.length > 0 && (
          <div style={{ marginTop: 'var(--space-4)' }}>
            <ReteachCards cards={result.reteach} />
          </div>
        )}
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
        {started.reteach && started.reteach.length > 0 && current === 0 && (
          <div className="stack" style={{ marginBottom: 'var(--space-3)' }}>
            <ReteachCards cards={started.reteach} />
          </div>
        )}
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
      <div className="chips" style={{ marginBottom: 'var(--space-3)' }} role="tablist" aria-label={t('quiz')}>
        <button
          role="tab"
          aria-selected={tab === 'quiz'}
          className={cn('chip', tab === 'quiz' && 'active')}
          onClick={() => setTab('quiz')}
        >
          {t('startQuiz')}
        </button>
        <button
          role="tab"
          aria-selected={tab === 'revision'}
          className={cn('chip', tab === 'revision' && 'active')}
          onClick={() => setTab('revision')}
        >
          <Repeat2 size={14} aria-hidden /> {t('revisionTab')}
          {due && due.due_count > 0 && (
            <Badge tone="teal">{due.due_count}</Badge>
          )}
        </button>
        <button
          role="tab"
          aria-selected={tab === 'shorttest'}
          className={cn('chip', tab === 'shorttest' && 'active')}
          onClick={() => setTab('shorttest')}
        >
          <ClipboardCheck size={14} aria-hidden /> {t('stTitle')}
          {stMine && stMine.length > 0 && (
            <Badge tone="teal">{stMine.length}</Badge>
          )}
        </button>
        <button
          role="tab"
          aria-selected={tab === 'assigned'}
          className={cn('chip', tab === 'assigned' && 'active')}
          onClick={() => setTab('assigned')}
        >
          <ClipboardCheck size={14} aria-hidden /> {t('asTitle')}
          {asMine && asMine.length > 0 && (
            <Badge tone="teal">{asMine.length}</Badge>
          )}
        </button>
      </div>
      {tab === 'revision' ? (
        <div className="stack">
          {due && due.items.length === 0 && (
            <Card>
              <p className="muted" style={{ margin: 0 }}>{t('revisionEmpty')}</p>
            </Card>
          )}
          {due?.items.map((item) => (
            <Card key={item.id} className="row" style={{ padding: 'var(--space-3)' }}>
              <div className="row-main">
                <div className="row-title">{item.question}</div>
                <div className="row-sub">
                  {t('chapter')}: {item.chapter}
                </div>
                <div className="stack" style={{ marginTop: 'var(--space-2)' }}>
                  {item.options.map((opt, oi) => (
                    <button
                      key={oi}
                      className="btn btn-ghost"
                      style={{ textAlign: 'left', justifyContent: 'flex-start' }}
                      disabled={revisionBusy}
                      onClick={() => answerRevision(item, oi)}
                    >
                      {opt}
                    </button>
                  ))}
                  <p className="muted" style={{ margin: 0, fontSize: 'var(--fs-sm)' }}>
                    {t('revisionChoose')}
                  </p>
                </div>
              </div>
            </Card>
          ))}
          {error && <p className="error">{error}</p>}
        </div>
      ) : tab === 'shorttest' ? (
        <div className="stack">
          {(!stMine || stMine.length === 0) && (
            <Card>
              <p className="muted" style={{ margin: 0 }}>{t('stEmpty')}</p>
            </Card>
          )}
          {stMine?.map((st) => (
            <Card key={st.id} className="row" style={{ padding: 'var(--space-3)' }}>
              <div className="row-main">
                <div className="row-title">{st.chapter}</div>
                <div className="row-sub">
                  {st.subject} · {t('stMinutes', { n: st.duration_min })}
                  {st.expired && (
                    <Badge tone="warn"> {t('stExpired')}</Badge>
                  )}
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  style={{ marginTop: 'var(--space-2)' }}
                  disabled={st.attempt_id === null}
                  onClick={() => openShortTest(st)}
                >
                  {t('startQuiz')}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      ) : tab === 'assigned' ? (
        <div className="stack">
          {(!asMine || asMine.length === 0) && (
            <Card>
              <p className="muted" style={{ margin: 0 }}>{t('baNone')}</p>
            </Card>
          )}
          {asMine?.map((a) => (
            <Card key={a.id} className="row" style={{ padding: 'var(--space-3)' }}>
              <div className="row-main">
                <div className="row-title">{a.chapter}</div>
                <div className="row-sub">
                  {a.subject} · {t('baDue')}: {new Date(a.due_at).toLocaleString()}
                  {a.done ? (
                    <Badge tone="ok"> {t('baDone')}</Badge>
                  ) : a.overdue ? (
                    <Badge tone="warn"> {t('baOverdue')}</Badge>
                  ) : null}
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  style={{ marginTop: 'var(--space-2)' }}
                  disabled={a.done}
                  onClick={() => openAssigned(a)}
                >
                  {t('startQuiz')}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      ) : (
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
          <select className="select" value={subject} onChange={(e) => setSubject(e.target.value)}>
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
      )}
    </main>
  )
}
