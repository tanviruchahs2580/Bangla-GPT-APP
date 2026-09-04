import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookOpenText, MessageSquarePlus, Send, ThumbsUp, ThumbsDown, Check } from 'lucide-react'
import { get, post, postStream } from '../../api'
import type { ChatDoneEvent, ChatMessage, ConversationOut, SourceRef } from '../../types'
import { useAuth } from '../../AuthContext'
import { Badge, Button, Card } from '../../components/ui'
import { friendlyError } from '../../errors'
import { t } from '../../i18n'
import { SafeMarkdown } from '../../lib/safeMarkdown'

const SUBJECTS = [
  { value: 'science', label: 'বিজ্ঞান' },
  { value: 'mathematics', label: 'গণিত' },
  { value: 'bangla', label: 'বাংলা' },
]

export default function AITutorPage() {
  const { me } = useAuth()
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [subject, setSubject] = useState('science')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [thanks, setThanks] = useState<number | null>(null)
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

  const send = useCallback(async () => {
    const text = input.trim()
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
        { message: text, subject },
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

  const rate = async (messageId: number, rating: 1 | -1) => {
    try {
      await post('/feedback', { rating, message_id: messageId })
      setThanks(messageId)
      setTimeout(() => setThanks(null), 2000)
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

      <div className="chips" style={{ marginBottom: 'var(--space-3)' }}>
        {SUBJECTS.map((s) => (
          <button key={s.value} className={subject === s.value ? 'chip active' : 'chip'} onClick={() => setSubject(s.value)}>
            {s.label}
          </button>
        ))}
      </div>

      {conversations && conversations.length > 0 && (
        <div className="chips" style={{ marginBottom: 'var(--space-3)' }}>
          {conversations.slice(0, 8).map((c) => (
            <button
              key={c.id}
              className={conversationId === c.id ? 'chip active' : 'chip'}
              onClick={() => loadConversation(c.id)}
            >
              {c.title ?? `#${c.id}`}
            </button>
          ))}
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
                {m.role === 'assistant' ? <SafeMarkdown content={m.content} /> : m.content}
              </div>
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
                      <span className="source-chip" key={si}>
                        {s.chapter || s.book}
                      </span>
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
          <Button variant="primary" onClick={send} disabled={streaming || !input.trim()}>
            <Send size={18} aria-hidden />
          </Button>
        </div>
        {me && (
          <span className="muted" style={{ fontSize: 'var(--fs-xs)' }}>
            {t('continueTutor')}
          </span>
        )}
      </Card>
    </main>
  )
}
