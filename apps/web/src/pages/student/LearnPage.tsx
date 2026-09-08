import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { BookOpen, Download, FileText } from 'lucide-react'
import { getChapterContent, getLearnProgress, getSubjectChapters, getSubjects, post, upsertLearnProgress } from '../../api'
import type { AskResponse, ChapterSummaryOut, QuizResult, QuizStarted, SubjectOut } from '../../types'
import { useAuth } from '../../AuthContext'
import { Card } from '../../components/ui'
import { t } from '../../i18n'
import { cn } from '../../lib/cn'
import { chapterBadge, ttsSupported as ttsAvailable } from '../../lib/progress'
import { SafeMarkdown } from '../../lib/safeMarkdown'
import { fetchChapterWithOfflineFallback, loadChapter, saveChapter } from '../../lib/offlineStore'
import { getLowData } from '../../lib/lowData'

const EMOJI: Record<string, string> = {
  science: '🔬',
  mathematics: '📐',
  bangla: '📖',
  6: '🔬',
  7: '🧲',
  8: '🧪',
  9: '⚡',
  10: '🧬',
}

export function LearnPage() {
  const { me } = useAuth()
  const navigate = useNavigate()
  const [selected, setSelected] = useState<number>(me?.class_level ?? 6)

  const classes = Array.from({ length: 12 }, (_, i) => i + 1)
  const subjectsQuery = useQuery({
    queryKey: ['subjects', selected],
    queryFn: () => getSubjects(selected),
  })
  const [activeSubject, setActiveSubject] = useState<string | null>(null)
  const chaptersQuery = useQuery({
    queryKey: ['chapters', activeSubject, selected],
    queryFn: () => getSubjectChapters(activeSubject!, selected),
    enabled: !!activeSubject,
  })
  const progressQuery = useQuery({
    queryKey: ['learnProgress', activeSubject, selected],
    queryFn: () => getLearnProgress(activeSubject!, selected),
    enabled: !!activeSubject,
  })
  const progressMap = new Map((progressQuery.data ?? []).map((p) => [p.chapter, p]))

  const subjects = subjectsQuery.data ?? []

  return (
    <main className="shell-main">
      <section className="section-head">
        <h2>{t('subjects')}</h2>
      </section>

      <div className="chips" role="group" aria-label={t('selectClass')} style={{ marginBottom: 'var(--space-4)' }}>
        {classes.map((c) => (
          <button
            key={c}
            className={cn('chip', selected === c && 'active')}
            onClick={() => {
              setSelected(c)
              setActiveSubject(null)
            }}
          >
            {t('classLabel')} {c}
          </button>
        ))}
      </div>

      {subjectsQuery.isLoading ? (
        <div className="stack">
          <div className="skeleton" style={{ height: 80 }} />
          <div className="skeleton" style={{ height: 80 }} />
        </div>
      ) : (
        <div className="subject-grid">
          {subjects.map((s: SubjectOut) => (
            <button
              key={s.subject}
              className={cn('subject-card', activeSubject === s.subject && 'active')}
              style={activeSubject === s.subject ? { borderColor: 'var(--brand)' } : {}}
              onClick={() => setActiveSubject((cur) => (cur === s.subject ? null : s.subject))}
            >
              <span className="subject-emoji">{EMOJI[s.subject] ?? '📘'}</span>
              <div className="subject-name">{s.subject}</div>
              <div className="subject-meta">{t('classLabel')} {s.class_levels.join(', ')}</div>
            </button>
          ))}
        </div>
      )}

      {activeSubject && (
        <>
          <section className="section-head">
            <h2>
              {t('chapters')} · {activeSubject}
            </h2>
          </section>
          <div className="stack">
            {chaptersQuery.isLoading ? (
              <Card>
                <div className="skeleton" style={{ height: 16 }} />
              </Card>
            ) : (chaptersQuery.data ?? []).length === 0 ? (
              <Card>
                <div className="center muted">{t('noChapters')}</div>
              </Card>
            ) : (
              (chaptersQuery.data ?? []).map((ch: ChapterSummaryOut) => {
                const prog = progressMap.get(ch.chapter)
                const badgeKind = chapterBadge(prog)
                const badge = badgeKind === 'done' ? '✓' : badgeKind === 'reading' ? '○' : null
                const bm = prog?.bookmarked ? '🔖' : ''
                return (
                  <Card key={ch.chapter} className="row" style={{ padding: 'var(--space-4)' }}>
                    <span className="quick-icon" style={{ background: 'var(--teal-soft)', color: 'var(--teal-strong)' }}>
                      <FileText size={20} aria-hidden />
                    </span>
                    <div className="row-main">
                      <div className="row-title">
                        {ch.chapter} {badge && <span className={prog?.completed ? 'badge badge-teal' : 'badge'} style={{ marginLeft: 6 }}>{badge}</span>} {bm && <span style={{ marginLeft: 4 }}>{bm}</span>}
                      </div>
                      <div className="row-sub">
                        {t('preview')}: {ch.excerpt}
                      </div>
                    </div>
                    <button className="btn btn-soft btn-sm" onClick={() => navigate(`/student/learn/${encodeURIComponent(activeSubject)}/${encodeURIComponent(ch.chapter)}?class=${selected}`)}>
                      {t('readConcept')}
                    </button>
                  </Card>
                )
              })
            )}
          </div>
        </>
      )}
    </main>
  )
}

export function LearnChapterPage() {
  const { subject, chapter, searchParams } = useRouteParams()
  const navigate = useNavigate()
  const classLevel = Number(searchParams.get('class')) || undefined
  // S1.13: one normalized class number keeps the offline key stable
  const offlineClass = classLevel ?? 6

  const query = useQuery({
    queryKey: ['chapterContent', subject, chapter, classLevel],
    // S1.13: network first; a saved offline copy covers network failure.
    queryFn: () =>
      fetchChapterWithOfflineFallback(subject!, chapter!, offlineClass, () =>
        getChapterContent(subject!, chapter!, classLevel),
      ),
    enabled: !!subject && !!chapter,
  })

  const [fontScale, setFontScale] = useState(() => {
    try {
      const v = localStorage.getItem('fontScale')
      return v ? parseFloat(v) : 1
    } catch { return 1 }
  })
  const [speaking, setSpeaking] = useState(false)
  const [bookmarked, setBookmarked] = useState(false)
  // S1.3: unified workspace tabs — পড়া | অনুশীলন | জিজ্ঞাসা (no page exit).
  const [tab, setTab] = useState<'read' | 'practice' | 'ask'>('read')
  // S1.13: offline-copy availability + download button state
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)

  const progressQuery = useQuery({
    queryKey: ['learnProgressOne', subject, chapter, classLevel],
    queryFn: () => getLearnProgress(subject!, classLevel),
    enabled: !!subject && !!chapter,
  })

  useEffect(() => {
    const p = (progressQuery.data ?? []).find((x) => x.chapter === chapter)
    if (p) setBookmarked(p.bookmarked)
  }, [progressQuery.data, chapter])

  useEffect(() => {
    if (!subject || !chapter) return
    let alive = true
    loadChapter(subject, chapter, offlineClass)
      .then((rec) => { if (alive) setSaved(!!rec) })
      .catch(() => {})
    return () => { alive = false }
  }, [subject, chapter, offlineClass])

  useEffect(() => {
    if (subject && chapter && classLevel) {
      try {
        localStorage.setItem('lastChapter', JSON.stringify({ subject, chapter, class_level: classLevel }))
        localStorage.setItem('fontScale', String(fontScale))
      } catch {}
    }
  }, [subject, chapter, classLevel, fontScale])

  // Mark read progress on view
  useEffect(() => {
    if (!query.data || !subject || !chapter || !classLevel) return
    const t = setTimeout(() => {
      upsertLearnProgress({ subject, chapter, class_level: classLevel, read_pct: 40 }).catch(() => {})
    }, 1500)
    const onScroll = () => {
      const pct = Math.min(100, Math.round((window.scrollY / Math.max(1, document.body.scrollHeight - window.innerHeight)) * 100))
      if (pct > 70) upsertLearnProgress({ subject, chapter, class_level: classLevel, read_pct: pct, completed: pct > 90 }).catch(() => {})
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => { clearTimeout(t); window.removeEventListener('scroll', onScroll) }
  }, [query.data, subject, chapter, classLevel])

  const toggleBookmark = async () => {
    if (!subject || !chapter || !classLevel) return
    const next = !bookmarked
    setBookmarked(next)
    try { await upsertLearnProgress({ subject, chapter, class_level: classLevel, bookmarked: next }) } catch {}
  }

  const speak = () => {
    try {
      if (!('speechSynthesis' in window) || !content) return
      if (speaking) { window.speechSynthesis.cancel(); setSpeaking(false); return }
      const text = content.sections.map((s) => `${s.section} ${s.text}`).join(' ')
      const utter = new SpeechSynthesisUtterance(text)
      utter.lang = 'bn-BD'
      utter.onend = () => setSpeaking(false)
      utter.onerror = () => setSpeaking(false)
      setSpeaking(true)
      window.speechSynthesis.speak(utter)
    } catch { setSpeaking(false) }
  }

  const content = query.data?.content
  const offlineCopy = query.data?.offline === true
  const ttsSupported = ttsAvailable()

  const download = async () => {
    if (!content || !subject || !chapter) return
    setSaving(true)
    try {
      await saveChapter(subject, chapter, offlineClass, content)
      setSaved(true)
    } catch {
      /* storage may be unavailable; the offline copy stays optional */
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="shell-main">
      <button className="btn btn-ghost btn-sm" onClick={() => navigate(-1)} style={{ marginBottom: 'var(--space-3)' }}>
        ← {t('back')}
      </button>
      {query.isLoading ? (
        <Card>
          <div className="skeleton" style={{ height: 20 }} />
          <div className="skeleton" style={{ height: 14 }} />
          <div className="skeleton" style={{ height: 120 }} />
        </Card>
      ) : query.isError || !content ? (
        <Card>
          <div className="center muted">{t('noChapters')}</div>
        </Card>
      ) : (
        <Card>
          <div className="row-flex" style={{ marginBottom: 'var(--space-2)', flexWrap: 'wrap' }}>
            <span className="badge badge-teal">{content.subject}</span>
            <span className="badge">{t('classLabel')} {content.class_level}</span>
            <button className={`btn btn-sm ${bookmarked ? 'btn-teal' : 'btn-ghost'}`} onClick={toggleBookmark} aria-label="bookmark">
              {bookmarked ? '🔖 বুকমার্ক' : '☆ বুকমার্ক'}
            </button>
            {ttsSupported && (
              <button className="btn btn-sm btn-ghost" onClick={speak} aria-label="tts">
                {speaking ? '⏹️ থামুন' : '🔊 শুনুন'}
              </button>
            )}
            {offlineCopy && <span className="badge">{t('offlineBadge')}</span>}
            <button
              className={`btn btn-sm ${saved ? 'btn-teal' : 'btn-ghost'}`}
              onClick={download}
              disabled={saving}
              aria-label={t('downloadChapter')}
            >
              <Download size={14} aria-hidden /> {saved ? t('downloaded') : t('downloadChapter')}
            </button>
            <span className="row-flex" style={{ gap: 6, marginLeft: 'auto' }}>
              <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>A</span>
              <input type="range" min={0.8} max={1.4} step={0.1} value={fontScale} onChange={(e) => setFontScale(parseFloat(e.target.value))} style={{ width: 90 }} aria-label="font size" />
              <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>A+</span>
            </span>
          </div>

          {/* S1.3: in-page tabs — read / practice / ask without leaving the chapter */}
          <div className="chips" role="tablist" aria-label="workspace" style={{ margin: 'var(--space-3) 0 var(--space-4)' }}>
            {(['read', 'practice', 'ask'] as const).map((k) => (
              <button
                key={k}
                role="tab"
                aria-selected={tab === k}
                className={cn('chip', tab === k && 'active')}
                onClick={() => setTab(k)}
              >
                {k === 'read' ? t('tabRead') : k === 'practice' ? t('tabPractice') : t('tabAsk')}
              </button>
            ))}
          </div>

          {tab === 'read' && (
            <>
              <h1 className="card-title" style={{ marginTop: 'var(--space-2)' }}>{content.chapter}</h1>
              <p className="muted">
                <BookOpen size={15} style={{ verticalAlign: 'middle' }} aria-hidden /> {content.book}
              </p>
              <div className="md stack" style={{ marginTop: 'var(--space-4)', fontSize: `${fontScale}em` }}>
                {content.sections.map((s, i) => (
                  <div key={i}>
                    {s.section && <h3>{s.section}</h3>}
                    <SafeMarkdown content={s.text} />
                  </div>
                ))}
              </div>
            </>
          )}
          {tab === 'practice' && (
            <ChapterPractice subject={content.subject} chapter={content.chapter} classLevel={content.class_level} />
          )}
          {tab === 'ask' && (
            <ChapterAsk subject={content.subject} chapter={content.chapter} classLevel={content.class_level} />
          )}
        </Card>
      )}
    </main>
  )
}

function useRouteParams(): { subject: string | null; chapter: string | null; searchParams: URLSearchParams } {
  const parts = window.location.pathname.split('/').filter(Boolean)
  // /student/learn/{subject}/{chapter}
  const idx = parts.indexOf('learn')
  const subject = idx >= 0 ? parts[idx + 1] ?? null : null
  const chapter = idx >= 0 ? parts[idx + 2] ?? null : null
  return { subject, chapter: chapter ? decodeURIComponent(chapter) : null, searchParams: new URLSearchParams(window.location.search) }
}

/** S1.3 অনুশীলন tab: mini quiz with the chapter preselected, no page exit. */
function ChapterPractice({ subject, chapter, classLevel }: { subject: string; chapter: string; classLevel: number }) {
  const { me } = useAuth()
  const [started, setStarted] = useState<QuizStarted | null>(null)
  const [answers, setAnswers] = useState<Record<number, number>>({})
  const [current, setCurrent] = useState(0)
  const [result, setResult] = useState<QuizResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await post<QuizStarted>('/quizzes', {
        student_id: me?.profile_id,
        class_level: classLevel,
        subject,
        chapter,
        num_questions: 5,
      })
      setStarted(res)
      setAnswers({})
      setCurrent(0)
      setResult(null)
    } catch (e) {
      const detail = (e as { rawDetail?: { message?: string } }).rawDetail
      setError(typeof detail === 'object' && detail?.message ? detail.message : t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  const submit = async () => {
    if (!started) return
    setBusy(true)
    try {
      const res = await post<QuizResult>(`/quizzes/${started.attempt_id}/submit`, {
        answers: started.questions.map((_, i) => answers[i] ?? -1),
      })
      setResult(res)
      setStarted(null)
    } catch {
      setError(t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    return (
      <div className="stack">
        <div className="center">
          <div className="stat-value">{Math.round(result.score_pct)}%</div>
          <div className="muted">{t('correctOutOf', { correct: result.correct, total: result.total })}</div>
        </div>
        {result.review.map((r, i) => (
          <Card key={i} style={{ padding: 'var(--space-3)' }}>
            <div className="row-title">{r.question_text}</div>
            <div className="row-sub">
              {r.is_correct ? '✓' : `✗ — ${r.options[r.correct_index] ?? ''}`}
            </div>
          </Card>
        ))}
        <button className="btn btn-soft" onClick={start} disabled={busy}>{t('startQuiz')} ↻</button>
      </div>
    )
  }

  if (started) {
    const q = started.questions[current]
    const chosen = answers[current]
    return (
      <div className="stack">
        <div className="row-flex">
          <span className="badge">{current + 1}/{started.questions.length}</span>
          <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{chapter}</span>
        </div>
        <div className="row-title" style={{ fontSize: 'var(--fs-lg)' }}>{q.question_text}</div>
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
        <div className="row-flex" style={{ justifyContent: 'space-between' }}>
          <button className="btn btn-ghost btn-sm" disabled={current === 0} onClick={() => setCurrent((c) => c - 1)}>
            ← {t('previousQuestion')}
          </button>
          {current < started.questions.length - 1 ? (
            <button className="btn btn-primary btn-sm" onClick={() => setCurrent((c) => c + 1)}>
              {t('nextQuestion')} →
            </button>
          ) : (
            <button className="btn btn-teal btn-sm" onClick={submit} disabled={busy}>{t('finishQuiz')}</button>
          )}
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    )
  }

  return (
    <div className="stack center">
      <p className="muted">{t('practiceThisChapter')} — {chapter}</p>
      <button className="btn btn-primary" onClick={start} disabled={busy || !me?.profile_id}>
        {t('startQuiz')}
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

/** S1.3 জিজ্ঞাসা tab: tutor scoped to this chapter via the chapter context chip. */
function ChapterAsk({ subject, chapter, classLevel }: { subject: string; chapter: string; classLevel: number }) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<AskResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const ask = async () => {
    const q = question.trim()
    if (q.length < 3 || busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await post<AskResponse>('/tutor/ask', {
        question: q,
        class_level: classLevel,
        subject,
        chapter,
        low_data: getLowData(),
      })
      setAnswer(res)
      setQuestion('')
    } catch {
      setError(t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="row-flex" style={{ gap: 6, flexWrap: 'wrap' }}>
        <span className="badge badge-teal">{t('contextChip')}: {chapter}</span>
      </div>
      <div className="row-flex" style={{ gap: 'var(--space-2)' }}>
        <input
          className="input"
          style={{ flex: 1 }}
          value={question}
          placeholder={t('askAboutChapter')}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void ask() }}
        />
        <button className="btn btn-primary" onClick={ask} disabled={busy || question.trim().length < 3}>
          {t('send')}
        </button>
      </div>
      {busy && <p className="muted">{t('thinking')}</p>}
      {error && <p className="error">{error}</p>}
      {answer && (
        <Card style={{ padding: 'var(--space-4)' }}>
          <div style={{ marginBottom: 'var(--space-2)' }}>
            <span className={answer.grounded ? 'badge badge-teal' : 'badge'}>
              {answer.grounded ? t('supportedBadge') : t('unsupportedBadge')}
            </span>
          </div>
          <SafeMarkdown content={answer.answer} />
          {answer.sources.length > 0 && (
            <p className="muted" style={{ fontSize: 'var(--fs-sm)', marginTop: 'var(--space-2)' }}>
              {t('chapter')}: {answer.sources[0].chapter}
            </p>
          )}
        </Card>
      )}
    </div>
  )
}
