import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase, del, get, post, postStream } from '../api'
import type { MeResponse } from '../api'
import { t } from '../i18n'
import type {
  ChatDoneEvent,
  ChatMessage,
  ConversationOut,
  QuizResult,
  QuizStarted,
  SourceRef,
  StudentProgress,
} from '../types'

interface DraftMsg {
  role: 'user' | 'assistant'
  content: string
  grounded?: boolean | null
  sources?: SourceRef[]
}

export default function StudentDashboard({ me }: { me: MeResponse }) {
  const studentId = me.profile_id

  // ── chat state ────────────────────────────────────────────────────────
  const [conversations, setConversations] = useState<ConversationOut[]>([])
  const [activeConv, setActiveConv] = useState<number | null>(null)
  const [messages, setMessages] = useState<(ChatMessage | DraftMsg)[]>([])
  const [draft, setDraft] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)
  const [subject, setSubject] = useState('science')
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  // ── quiz state ────────────────────────────────────────────────────────
  const [numQuestions, setNumQuestions] = useState(5)
  const [quizSubject, setQuizSubject] = useState('science')
  const [quiz, setQuiz] = useState<QuizStarted | null>(null)
  const [choices, setChoices] = useState<number[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<QuizResult | null>(null)
  const [quizError, setQuizError] = useState<string | null>(null)

  // ── progress state ────────────────────────────────────────────────────
  const [progress, setProgress] = useState<StudentProgress | null>(null)

  const loadConversations = useCallback(() => {
    get<ConversationOut[]>('/tutor/conversations')
      .then(setConversations)
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  useEffect(() => {
    if (studentId === null) return
    get<StudentProgress>(`/students/${studentId}/progress`)
      .then(setProgress)
      .catch(() => undefined)
  }, [studentId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function openConversation(id: number) {
    if (streaming) return
    setActiveConv(id)
    try {
      const history = await get<ChatMessage[]>(`/tutor/conversations/${id}/messages`)
      setMessages(history.map((m) => ({ ...m, sources: m.sources ?? [] })))
    } catch {
      setMessages([])
    }
  }

  function newConversation() {
    setActiveConv(null)
    setMessages([])
    setChatError(null)
  }

  async function send(e: React.FormEvent) {
    e.preventDefault()
    const text = draft.trim()
    if (text.length < 3 || streaming) return
    setChatError(null)
    setDraft('')
    setStreaming(true)
    setMessages((prev) => [...prev, { role: 'user', content: text }, { role: 'assistant', content: '' }])
    let convId = activeConv
    try {
      if (convId === null) {
        const created = await post<ConversationOut>('/tutor/conversations', {})
        convId = created.id
        setActiveConv(created.id)
        loadConversations()
      }
      const done = await postStream<ChatDoneEvent>(
        `/tutor/conversations/${convId}/messages/stream`,
        { message: text, subject },
        (token) =>
          setMessages((prev) => {
            const copy = [...prev]
            const last = copy[copy.length - 1] as DraftMsg
            copy[copy.length - 1] = { ...last, content: last.content + token }
            return copy
          }),
      )
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          role: 'assistant',
          content: done.answer,
          grounded: done.grounded,
          sources: done.sources,
          id: done.message_id,
        },
      ])
      loadConversations()
    } catch {
      setChatError(t('errorGeneric'))
      setMessages((prev) => prev.filter((m) => (m as DraftMsg).content !== ''))
    } finally {
      setStreaming(false)
    }
  }

  async function rate(messageId: number | undefined, rating: 1 | -1) {
    if (!messageId) return
    setMessages((prev) =>
      prev.map((m) => ('id' in m && m.id === messageId ? { ...m, rating } : m)),
    )
    post('/feedback', { rating, message_id: messageId }).catch(() => undefined)
  }

  async function startQuiz() {
    if (studentId === null || submitting) return
    setQuizError(null)
    setResult(null)
    try {
      const started = await post<QuizStarted>('/quizzes', {
        student_id: studentId,
        class_level: me.class_level ?? undefined,
        subject: quizSubject,
        num_questions: numQuestions,
      })
      setQuiz(started)
      setChoices(Array(started.questions.length).fill(0))
    } catch {
      setQuizError(t('errorGeneric'))
    }
  }

  async function submitQuiz() {
    if (!quiz || submitting) return
    setSubmitting(true)
    setQuizError(null)
    try {
      const res = await post<QuizResult>(`/quizzes/${quiz.attempt_id}/submit`, { answers: choices })
      setResult(res)
      setQuiz(null)
      if (studentId !== null) {
        get<StudentProgress>(`/students/${studentId}/progress`).then(setProgress).catch(() => undefined)
      }
    } catch {
      setQuizError(t('errorGeneric'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <h1 className="page-title">
        {t('appName')} — {me.name} ({t('className').replace(/\s*\(.*\)/, '')} {me.class_level})
      </h1>

      {/* ── Tutor chat ─────────────────────────────────────────────── */}
      <section className="card" aria-label="Tutor chat">
        <h2>{t('askPlaceholder') ? 'টিউটর' : 'টিউটর'}</h2>
        <div className="grid-2" style={{ marginBottom: 12 }}>
          <div>
            <label htmlFor="subj">{t('subject')}</label>
            <select id="subj" value={subject} onChange={(e) => setSubject(e.target.value)}>
              <option value="science">বিজ্ঞান</option>
              <option value="math">গণিত</option>
              <option value="bangla">বাংলা</option>
            </select>
          </div>
        </div>

        <div className="chat-shell">
          <aside aria-label={t('conversations')}>
            <button className="secondary" style={{ width: '100%', marginBottom: 8 }} onClick={newConversation}>
              ＋ {t('newChat')}
            </button>
            <div className="conv-list">
              {conversations.map((c) => (
                <button
                  key={c.id}
                  className={`conv-item${c.id === activeConv ? ' active' : ''}`}
                  onClick={() => openConversation(c.id)}
                >
                  {c.title ?? `${t('newChat')} #${c.id}`}
                </button>
              ))}
              {conversations.length === 0 && (
                <span className="muted">{t('newChat')} →</span>
              )}
            </div>
          </aside>

          <div className="chat-panel">
            <div className="messages" aria-live="polite" aria-relevant="additions text">
              {messages.length === 0 && (
                <p className="muted">{t('askPlaceholder')}</p>
              )}
              {messages.map((m, i) => {
                const isLastAssistant =
                  m.role === 'assistant' && i === messages.length - 1 && streaming
                return (
                  <div key={'id' in m && m.id ? m.id : `draft-${i}`} className={`msg ${m.role}`}>
                    {m.content ? m.content : isLastAssistant ? (
                      <span className="typing-dots" aria-label={t('thinking')}>
                        <span /><span /><span />
                      </span>
                    ) : null}
                    {'grounded' in m && m.grounded != null && !isLastAssistant && (
                      <div className="meta">
                        <span className={`badge ${m.grounded ? 'grounded' : 'refused'}`}>
                          {m.grounded ? t('supportedBadge') : t('unsupportedBadge')}
                        </span>
                      </div>
                    )}
                    {'sources' in m && m.sources && m.sources.length > 0 && (
                      <ul className="sources">
                        {m.sources.map((s, j) => (
                          <li key={j}>📘 {s.book} · {s.chapter}{s.section ? ` · ${s.section}` : ''}</li>
                        ))}
                      </ul>
                    )}
                    {m.role === 'assistant' && !streaming && 'id' in m && m.id && (
                      <div className="meta">
                        <button
                          className={`rate-btn${m.rating === 1 ? ' on-up' : ''}`}
                          title={t('rateUp')}
                          onClick={() => rate(m.id, 1)}
                        >
                          👍
                        </button>
                        <button
                          className={`rate-btn${m.rating === -1 ? ' on-down' : ''}`}
                          title={t('rateDown')}
                          onClick={() => rate(m.id, -1)}
                        >
                          👎
                        </button>
                        {m.rating != null && <span className="muted">{t('thanksFeedback')}</span>}
                      </div>
                    )}
                  </div>
                )
              })}
              <div ref={messagesEndRef} />
            </div>

            <form className="composer" onSubmit={send}>
              <textarea
                aria-label={t('askPlaceholder')}
                placeholder={t('askPlaceholder')}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void send(e)
                  }
                }}
              />
              <button className="primary" type="submit" disabled={streaming || draft.trim().length < 3}>
                {streaming ? <span className="spinner" aria-hidden /> : t('send')}
              </button>
            </form>
            {chatError && <p className="error" role="alert" style={{ padding: '0 14px' }}>{chatError}</p>}
          </div>
        </div>
      </section>

      {/* ── Quiz ───────────────────────────────────────────────────── */}
      <section className="card" aria-label={t('quizTitle')}>
        <h2>{t('quizTitle')}</h2>
        {!quiz && !result && (
          <>
            <div className="grid-2">
              <div>
                <label htmlFor="qsub">{t('subject')}</label>
                <select id="qsub" value={quizSubject} onChange={(e) => setQuizSubject(e.target.value)}>
                  <option value="science">বিজ্ঞান</option>
                  <option value="math">গণিত</option>
                  <option value="bangla">বাংলা</option>
                </select>
              </div>
              <div>
                <label htmlFor="nq">{t('questionCount')}</label>
                <input
                  id="nq"
                  type="number"
                  min={1}
                  max={10}
                  value={numQuestions}
                  onChange={(e) => setNumQuestions(Number(e.target.value))}
                />
              </div>
            </div>
            <button className="primary" onClick={startQuiz}>{t('startQuiz')}</button>
          </>
        )}
        {quiz && (
          <form onSubmit={(e) => { e.preventDefault(); void submitQuiz() }}>
            {quiz.note && (
              <p className="muted" role="status">
                {t('partialQuizNote', { got: quiz.questions.length, want: quiz.requested })}
              </p>
            )}
            {quiz.questions.map((qq, qi) => (
              <fieldset key={qq.id} style={{ marginBottom: 16 }}>
                <legend>
                  {qi + 1}. {qq.question_text}
                </legend>
                {qq.options.map((opt, oi) => (
                  <label key={oi} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                    <input
                      type="radio"
                      name={qq.id}
                      checked={choices[qi] === oi}
                      onChange={() => setChoices(choices.map((c, i) => (i === qi ? oi : c)))}
                      style={{ width: 'auto', margin: 0 }}
                    />
                    {opt}
                  </label>
                ))}
              </fieldset>
            ))}
            <button className="primary" type="submit" disabled={submitting}>
              {submitting ? <span className="spinner" aria-hidden /> : t('submitQuiz')}
            </button>
          </form>
        )}
        {result && (
          <>
            <p className="ok" role="status">
              {t('accuracy')}: {result.correct}/{result.total} ({result.score_pct}%)
            </p>
            {result.review.map((r, i) => (
              <div key={i} className="review-item">
                <strong>{r.question_text}</strong>
                <p className={r.is_correct ? 'ok' : 'error'}>
                  {t('correct')}: {r.options[r.correct_index]}
                  {!r.is_correct && ` — ${t('weak')}: ${r.options[r.chosen]}`}
                </p>
                <span className="muted">{t('chapter')}: {r.chapter}</span>
              </div>
            ))}
            <button className="secondary" onClick={() => setResult(null)}>{t('startQuiz')}</button>
          </>
        )}
        {quizError && <p className="error" role="alert">{quizError}</p>}
      </section>

      {/* ── Progress ───────────────────────────────────────────────── */}
      <section className="card" aria-label={t('progressTitle')}>
        <h2>{t('progressTitle')}</h2>
        {progress && (
          <>
            <div className="stat-row">
              <div className="stat">
                <div className="num">{progress.attempts_graded}</div>
                <div className="lbl">{t('gradedQuizzes')}</div>
              </div>
              <div className="stat">
                <div className="num">{progress.avg_score_pct ?? '—'}%</div>
                <div className="lbl">{t('avgScore')}</div>
              </div>
              <div className="stat">
                <div className="num">{progress.weak_chapters.length}</div>
                <div className="lbl">{t('weakChapters')}</div>
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
                          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            <span className="accuracy-bar" aria-hidden>
                              <span style={{ width: `${Math.min(c.accuracy, 100)}%` }} />
                            </span>
                            {c.accuracy}%
                            {c.accuracy < 60 && <span className="badge weak">{t('weak')}</span>}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      {/* ── Account ────────────────────────────────────────────────── */}
      <AccountCard />
    </>
  )
}

function AccountCard() {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  async function doDelete() {
    setBusy(true)
    try {
      await del('/users/me')
      window.location.href = '/login'
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" aria-label={t('account')}>
      <h3>{t('account')}</h3>
      <a href={`${apiBase}/users/me/export`} download className="btn secondary" style={{ marginRight: 8 }}>
        {t('exportData')}
      </a>
      <button className="danger" onClick={() => setConfirming(true)}>
        {t('deleteAccount')}
      </button>
      <p className="muted" style={{ marginTop: 8 }}>
        {t('deleteWarning')}
      </p>
      {confirming && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="del-title">
          <div className="modal">
            <h3 id="del-title">{t('deleteAccount')}</h3>
            <p>{t('deleteWarning')}</p>
            <div className="modal-actions">
              <button className="secondary" onClick={() => setConfirming(false)} autoFocus>
                {t('cancel')}
              </button>
              <button className="danger" onClick={doDelete} disabled={busy}>
                {busy ? <span className="spinner" aria-hidden /> : t('confirmDelete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
