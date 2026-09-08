import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpenText, Check, MessageSquarePlus, Pencil, Search, Send, ThumbsUp, ThumbsDown, Trash2, X } from 'lucide-react'
import { del, get, patch, post, postStream } from '../../api'
import type { ChatDoneEvent, ChatMessage, ConversationOut, MessageSearchHit, SourceRef } from '../../types'
import { useAuth } from '../../AuthContext'
import { Badge, Button, Card } from '../../components/ui'
import { VoiceButton } from '../../components/VoiceButton'
import { friendlyError } from '../../errors'
import { t } from '../../i18n'
import { getLowData } from '../../lib/lowData'
import { explainMessage, type QuizExplainPayload } from '../../lib/quizExplain'
import { SafeMarkdown } from '../../lib/safeMarkdown'
import { parseStructuredAnswer } from '../../lib/structuredAnswer'
import { SECTION } from '../../lib/structuredAnswer'

const SUBJECTS = [
  { value: 'science', label: 'বিজ্ঞান' },
  { value: 'mathematics', label: 'গণিত' },
  { value: 'bangla', label: 'বাংলা' },
]

export default function AITutorPage() {
  const { me } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [subject, setSubject] = useState('science')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [thanks, setThanks] = useState<number | null>(null)
  // S1.6: source → evidence modal.
  const [evidence, setEvidence] = useState<SourceRef | null>(null)
  // S1.8: history search + rename/delete.
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<MessageSearchHit[] | null>(null)
  const [renamingId, setRenamingId] = useState<number | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const viewportRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const { data: conversations, refetch: refetchConvs } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => get<ConversationOut[]>('/tutor/conversations'),
  })

  // Cancel an in-flight SSE stream when the student leaves the page.
  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, streaming])

  const loadConversation = useCallback(async (id: number) => {
    setConversationId(id)
    setMessages([])
    setError(null)
    try {
      const msgs = await get<ChatMessage[]>(`/tutor/conversations/${id}/messages`)
      setMessages(msgs)
    } catch {
      setError('লোড করা যায়নি')
    }
  }, [])

  const newChat = useCallback(async () => {
    try {
      const res = await post<ConversationOut>('/tutor/conversations', {})
      await refetchConvs()
      await loadConversation(res.id)
    } catch {
      setError('নতুন চ্যাট শুরু করা যায়নি')
    }
  }, [loadConversation, refetchConvs])

  const send = useCallback(async (preset?: string, opts?: { reteach?: boolean }) => {
    const text = (preset ?? input).trim()
    if (!text || streaming) return
    setInput('')
    setError(null)
    let id = conversationId
    if (!id) {
      try {
        const res = await post<ConversationOut>('/tutor/conversations', {})
        id = res.id
        setConversationId(id)
        await refetchConvs()
      } catch {
        setError('নতুন চ্যাট শুরু করা যায়নি')
        return
      }
    }
    setMessages((m) => [...m, { id: 0, role: 'user', content: text, grounded: null, sources: [] }])
    setStreaming(true)
    const acc = { text: '' }
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const undone = await postStream<ChatDoneEvent>(
        `/tutor/conversations/${id}/messages/stream`,
        {
          message: text,
          subject,
          low_data: getLowData(),
          ...(opts?.reteach ? { reteach: true } : {}),
        },
        (tok) => {
          acc.text += tok
          // live-update the trailing assistant bubble
          setMessages((m) => {
            const copy = [...m]
            const last = copy[copy.length - 1]
            if (last.role === 'assistant') last.content = acc.text
            else copy.push({ id: 0, role: 'assistant', content: acc.text, grounded: null, sources: [] })
            return copy
          })
        },
        { signal: controller.signal },
      )
      setMessages((m) => {
        const copy = [...m]
        const li = copy.findIndex((x) => x.id === undone.message_id)
        if (li >= 0) {
          copy[li] = { ...copy[li], content: acc.text, grounded: undone.grounded, refused_reason: undone.refused_reason, sources: undone.sources ?? [] }
        } else {
          copy.push({ id: undone.message_id, role: 'assistant', content: acc.text, grounded: undone.grounded, refused_reason: undone.refused_reason, sources: undone.sources ?? [] })
        }
        return copy
      })
    } catch (e) {
      if ((e as { name?: string })?.name === 'AbortError') return
      setError(friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ?? t('errorGeneric'))
    } finally {
      setStreaming(false)
      if (abortRef.current === controller) abortRef.current = null
    }
  }, [input, streaming, conversationId, subject, refetchConvs])

  // S1.7: a wrong quiz item can arrive here as `location.state.explain` —
  // ask once, then drop the explain payload so a refresh does not re-ask.
  const quizContextRef = useRef(false)
  const [backToResult, setBackToResult] = useState(false)
  useEffect(() => {
    const st = location.state as { explain?: QuizExplainPayload; backToResult?: boolean } | null
    if (!st?.explain || quizContextRef.current) return
    quizContextRef.current = true
    if (st.backToResult) setBackToResult(true)
    void send(explainMessage(st.explain))
    navigate(location.pathname, { replace: true, state: null })
  }, [location, navigate, send])

  // S1.11: the search box's "ask in Tutor" action hands the question over via
  // location.state.ask — ask it once, then clear the payload (like explain).
  const askSentRef = useRef(false)
  useEffect(() => {
    const st = location.state as { ask?: string } | null
    if (!st?.ask || askSentRef.current) return
    askSentRef.current = true
    void send(st.ask)
    navigate(location.pathname, { replace: true, state: null })
  }, [location, navigate, send])

  const rate = async (messageId: number, rating: 1 | -1) => {
    try {
      await post('/feedback', { rating, message_id: messageId })
      setThanks(messageId)
      setTimeout(() => setThanks(null), 2000)
    } catch {
      /* ignore */
    }
  }

  // S1.8: message search over this student's own history.
  const runSearch = async () => {
    const q = query.trim()
    if (q.length < 2) {
      setHits(null)
      return
    }
    try {
      setHits(await get<MessageSearchHit[]>(`/tutor/messages/search?q=${encodeURIComponent(q)}`))
    } catch {
      setHits([])
    }
  }

  const commitRename = async (id: number) => {
    const title = renameValue.trim()
    setRenamingId(null)
    if (!title) return
    try {
      await patch<ConversationOut>(`/tutor/conversations/${id}`, { title })
      await refetchConvs()
    } catch {
      /* keep old title on failure */
    }
  }

  const removeConversation = async (id: number) => {
    if (!window.confirm(t('deleteChatConfirm'))) return
    try {
      await del(`/tutor/conversations/${id}`)
      if (conversationId === id) {
        setConversationId(null)
        setMessages([])
      }
      await refetchConvs()
    } catch {
      /* ignore */
    }
  }

  return (
    <main className="shell-main">
      <section className="section-head">
        <h2>{t('aiTutor')}</h2>
        <Button variant="soft" size="sm" onClick={newChat}>
          <MessageSquarePlus size={16} aria-hidden /> {t('newChat')}
        </Button>
      </section>

      {backToResult && (
        // S1.7: back-link to the quiz result this explain loop came from.
        <Button variant="ghost" size="sm" style={{ marginBottom: 'var(--space-3)' }} onClick={() => navigate('/student/quiz?result=1')}>
          <ArrowLeft size={16} aria-hidden /> {t('backToQuizResult')}
        </Button>
      )}

      <div className="chips" style={{ marginBottom: 'var(--space-3)' }}>
        {SUBJECTS.map((s) => (
          <button key={s.value} className={subject === s.value ? 'chip active' : 'chip'} onClick={() => setSubject(s.value)}>
            {s.label}
          </button>
        ))}
      </div>

      {/* S1.8: history search */}
      <div className="row-flex" style={{ gap: '6px', marginBottom: 'var(--space-3)' }}>
        <input
          className="input"
          style={{ flex: 1 }}
          value={query}
          placeholder={t('searchHistory')}
          aria-label={t('searchHistory')}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && runSearch()}
        />
        <Button variant="ghost" size="sm" onClick={runSearch} aria-label={t('searchHistory')}>
          <Search size={16} aria-hidden />
        </Button>
      </div>
      {hits && (
        <div className="stack" style={{ marginBottom: 'var(--space-3)' }}>
          {hits.length === 0 && <span className="muted">{t('noResults')}</span>}
          {hits.slice(0, 6).map((h) => (
            <button
              key={h.message_id}
              className="btn btn-ghost"
              style={{ textAlign: 'left', justifyContent: 'flex-start' }}
              onClick={() => {
                void loadConversation(h.conversation_id)
                setHits(null)
                setQuery('')
              }}
            >
              <div>
                <div className="row-title">{h.conversation_title ?? `#${h.conversation_id}`}</div>
                <div className="row-sub">{h.snippet}</div>
              </div>
            </button>
          ))}
        </div>
      )}

      {conversations && conversations.length > 0 && (
        <div className="chips" style={{ marginBottom: 'var(--space-3)' }}>
          {conversations.slice(0, 8).map((c) =>
            renamingId === c.id ? (
              <input
                key={c.id}
                className="input"
                style={{ width: 160 }}
                autoFocus
                value={renameValue}
                aria-label={t('rename')}
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void commitRename(c.id)
                  if (e.key === 'Escape') setRenamingId(null)
                }}
                onBlur={() => void commitRename(c.id)}
              />
            ) : (
              <button
                key={c.id}
                className={conversationId === c.id ? 'chip active' : 'chip'}
                onClick={() => loadConversation(c.id)}
              >
                {c.title ?? `#${c.id}`}
                {conversationId === c.id && (
                  <span
                    role="button"
                    tabIndex={0}
                    aria-label={t('rename')}
                    style={{ marginLeft: 6 }}
                    onClick={(e) => {
                      e.stopPropagation()
                      setRenamingId(c.id)
                      setRenameValue(c.title ?? '')
                    }}
                    onKeyDown={(e) => e.key === 'Enter' && setRenamingId(c.id)}
                  >
                    <Pencil size={12} aria-hidden />
                  </span>
                )}
                <span
                  role="button"
                  tabIndex={0}
                  aria-label={t('deleteChat')}
                  style={{ marginLeft: 6 }}
                  onClick={(e) => {
                    e.stopPropagation()
                    void removeConversation(c.id)
                  }}
                  onKeyDown={(e) => e.key === 'Enter' && void removeConversation(c.id)}
                >
                  <Trash2 size={12} aria-hidden />
                </span>
              </button>
            ),
          )}
        </div>
      )}

      <Card style={{ display: 'flex', flexDirection: 'column' }}>
        <div
          ref={viewportRef}
          className="chat-thread"
          style={{ minHeight: '38vh', maxHeight: '52vh', overflowY: 'auto' }}
          aria-live="polite"
        >
          {messages.length === 0 && !streaming && (
            <div className="center muted" style={{ padding: 'var(--space-6)' }}>
              <BookOpenText size={40} aria-hidden style={{ opacity: 0.4 }} />
              <p>{t('askPlaceholder')}</p>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={m.id || i}>
              <div className={`bubble ${m.role}`}>
                {m.role === 'assistant' ? <AssistantContent content={m.content} /> : m.content}
              </div>
              {m.role === 'assistant' && i === messages.length - 1 && !streaming && m.grounded && (
                <div className="chips" role="group" aria-label={t('quickFollowups')} style={{ margin: '6px 0' }}>
                  <button className="chip" onClick={() => send(t('chipSimpler'))}>
                    {t('chipSimpler')}
                  </button>
                  <button className="chip" onClick={() => send(t('chipExample'))}>
                    {t('chipExample')}
                  </button>
                  <button className="chip" onClick={() => navigate(`/student/quiz?subject=${subject}`)}>
                    {t('chipQuiz')}
                  </button>
                </div>
              )}
              {m.role === 'assistant' && m.sources && m.sources.length > 0 && (
                <div className="sources">
                  {m.refused_reason ? (
                    <Badge tone="warn">{t('unsupportedBadge')}</Badge>
                  ) : (
                    <Badge tone="teal">
                      <Check size={12} aria-hidden /> {t('supportedBadge')}
                    </Badge>
                  )}
                  <div className="row-flex" style={{ gap: '6px', marginTop: '6px' }}>
                    {m.sources.map((s: SourceRef, si) => (
                      <button
                        className="source-chip"
                        key={si}
                        onClick={() => setEvidence(s)}
                        aria-label={`${t('evidenceTitle')}: ${s.chapter || s.book}`}
                      >
                        {s.chapter || s.book}
                      </button>
                    ))}
                  </div>
                  {m.id !== 0 && (
                    <div className="row-flex" style={{ gap: '6px', marginTop: '6px' }}>
                      <button className="icon-btn" style={{ width: 32, height: 32 }} aria-label={t('rateUp')} onClick={() => rate(m.id, 1)}>
                        {thanks === m.id ? <Check size={16} aria-hidden /> : <ThumbsUp size={16} aria-hidden />}
                      </button>
                      <button className="icon-btn" style={{ width: 32, height: 32 }} aria-label={t('rateDown')} onClick={() => rate(m.id, -1)}>
                        <ThumbsDown size={16} aria-hidden />
                      </button>
                      {m.grounded && (
                        <button
                          className="chip"
                          style={{ alignSelf: 'center' }}
                          onClick={() => {
                            // S1.5 'আমি বুঝিনি': re-ask the same question with the
                            // next teaching strategy (server rotates conversation strategy).
                            const q = [...messages.slice(0, i)].reverse().find((x) => x.role === 'user')?.content
                            if (q) send(q, { reteach: true })
                          }}
                        >
                          {t('reteach')}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          {streaming && (
            <div className="bubble assistant">
              <span className="typing-dots">
                <span /> <span /> <span />
              </span>
              <span className="visually-hidden">{t('thinking')}</span>
            </div>
          )}
        </div>

        {error && <p className="error" style={{ margin: 'var(--space-2) 0 0' }}>{error}</p>}

        <div className="chat-input">
          <input
            className="input"
            value={input}
            placeholder={t('askPlaceholder')}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            aria-label={t('askPlaceholder')}
          />
          <VoiceButton
            onTranscript={(text) => setInput((cur) => (cur ? cur + ' ' + text : text))}
          />
          <Button variant="primary" onClick={() => send()} disabled={streaming || !input.trim()}>
            <Send size={18} aria-hidden />
          </Button>
        </div>
        {me && (
          <span className="muted" style={{ fontSize: 'var(--fs-xs)' }}>
            {t('continueTutor')}
          </span>
        )}
      </Card>

      {evidence && <EvidenceModal source={evidence} onClose={() => setEvidence(null)} />}
    </main>
  )
}

/** S1.6 — full sanitized textbook evidence behind the source chip. */
function EvidenceModal({ source, onClose }: { source: SourceRef; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const path = [source.book, source.chapter, source.section].filter(Boolean).join(' › ')
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={t('evidenceTitle')} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3 style={{ margin: 0, fontSize: 'var(--fs-md)' }}>{t('evidenceTitle')}</h3>
          <button className="icon-btn" style={{ width: 32, height: 32 }} onClick={onClose} aria-label={t('close')}>
            <X size={16} aria-hidden />
          </button>
        </div>
        <p className="muted" style={{ margin: '0 0 var(--space-3)', fontSize: 'var(--fs-sm)' }}>
          {path}
          {source.page != null ? ` · ${t('page')} ${source.page}` : ''}
        </p>
        <blockquote
          style={{ margin: 0, padding: 'var(--space-3)', background: 'var(--bg)', borderRadius: 'var(--radius-md)', whiteSpace: 'pre-wrap' }}
        >
          {source.excerpt ?? source.chapter}
        </blockquote>
      </div>
    </div>
  )
}

/** S1.4 — renders the sectioned answer layout when present, plain markdown otherwise. */
function AssistantContent({ content }: { content: string }) {
  const parsed = parseStructuredAnswer(content)
  if (!parsed.structured) return <SafeMarkdown content={content} />
  return (
    <div className="structured-answer">
      {parsed.simple && (
        <section>
          <h4 className="section-label">{SECTION.simple.replace(/[:?]\s*$/, '')}</h4>
          <SafeMarkdown content={parsed.simple} />
        </section>
      )}
      {parsed.example && (
        <section>
          <h4 className="section-label">{SECTION.example.replace(/[:?]\s*$/, '')}</h4>
          <SafeMarkdown content={parsed.example} />
        </section>
      )}
      {parsed.points.length > 0 && (
        <section>
          <h4 className="section-label">{SECTION.points.replace(/[:?]\s*$/, '')}</h4>
          <ul>
            {parsed.points.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </section>
      )}
      {parsed.check && (
        <section className="check-question">
          <SafeMarkdown content={`${SECTION.check} ${parsed.check}`.trim()} />
        </section>
      )}
    </div>
  )
}
