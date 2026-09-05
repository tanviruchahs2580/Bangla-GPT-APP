import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { BookOpen, FileText } from 'lucide-react'
import { getChapterContent, getSubjectChapters, getSubjects } from '../../api'
import type { ChapterSummaryOut, SubjectOut } from '../../types'
import { useAuth } from '../../AuthContext'
import { Card } from '../../components/ui'
import { t } from '../../i18n'
import { cn } from '../../lib/cn'
import { SafeMarkdown } from '../../lib/safeMarkdown'

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
              (chaptersQuery.data ?? []).map((ch: ChapterSummaryOut) => (
                <Card key={ch.chapter} className="row" style={{ padding: 'var(--space-4)' }}>
                  <span className="quick-icon" style={{ background: 'var(--teal-soft)', color: 'var(--teal-strong)' }}>
                    <FileText size={20} aria-hidden />
                  </span>
                  <div className="row-main">
                    <div className="row-title">{ch.chapter}</div>
                    <div className="row-sub">
                      {t('preview')}: {ch.excerpt}
                    </div>
                  </div>
                  <button className="btn btn-soft btn-sm" onClick={() => navigate(`/student/learn/${encodeURIComponent(activeSubject)}/${encodeURIComponent(ch.chapter)}?class=${selected}`)}>
                    {t('readConcept')}
                  </button>
                </Card>
              ))
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

  const query = useQuery({
    queryKey: ['chapterContent', subject, chapter, classLevel],
    queryFn: () => getChapterContent(subject!, chapter!, classLevel),
    enabled: !!subject && !!chapter,
  })

  useEffect(() => {
    if (subject && chapter && classLevel) {
      try {
        localStorage.setItem('lastChapter', JSON.stringify({ subject, chapter, class_level: classLevel }))
      } catch {}
    }
  }, [subject, chapter, classLevel])

  const content = query.data

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
          <div className="row-flex" style={{ marginBottom: 'var(--space-2)' }}>
            <span className="badge badge-teal">{content.subject}</span>
            <span className="badge">{t('classLabel')} {content.class_level}</span>
          </div>
          <h1 className="card-title" style={{ marginTop: 'var(--space-2)' }}>{content.chapter}</h1>
          <p className="muted">
            <BookOpen size={15} style={{ verticalAlign: 'middle' }} aria-hidden /> {content.book}
          </p>
          <div className="md stack" style={{ marginTop: 'var(--space-4)' }}>
            {content.sections.map((s, i) => (
              <div key={i}>
                {s.section && <h3>{s.section}</h3>}
                <SafeMarkdown content={s.text} />
              </div>
            ))}
          </div>
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
