import { useCallback, useEffect, useState } from 'react'
import { apiBase, get, getToken, post } from '../api'
import { Badge } from '../components/ui'
import { CreateHub } from '../components/teacher/CreateHub'
import { friendlyError } from '../errors'
import { t } from '../i18n'
import type {
  AssignmentProgressRow,
  AssignmentRow,
  ClassAnalytics,
  ClassRoom,
  Coverage,
  ImportResult,
  LessonPlan,
  QPaper,
  RosterEntry,
  ShortTest,
  SupportPlanRow,
  WeakMatrix,
} from '../types'

const errText = (err: unknown): string =>
  friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ?? t('errorGeneric')

// S2.6: backend section keys -> i18n labels, in the eight-step teaching order.
const LESSON_SECTION_LABELS: Record<string, string> = {
  objective: 'lpSecObjective',
  previous_knowledge: 'lpSecPrevious',
  introduction: 'lpSecIntro',
  main_explanation: 'lpSecMain',
  activity: 'lpSecActivity',
  questions: 'lpSecQuestions',
  assessment: 'lpSecAssessment',
  homework: 'lpSecHomework',
}

// S2.7: heatmap bucket -> cell class (colors come from the design tokens only).
const heatClass = (acc: number | null): string =>
  acc === null ? 'wm-na' : acc < 40 ? 'wm-bad' : acc < 60 ? 'wm-mid' : 'wm-good'

const STAGE_KEYS: Record<string, string> = {
  concept: 'spStageConcept',
  practice: 'spStagePractice',
  assessment: 'spStageAssessment',
}

const stageLabel = (stage: string): string =>
  STAGE_KEYS[stage] ? t(STAGE_KEYS[stage] as Parameters<typeof t>[0]) : stage

// S3.3: coverage cell status -> badge label + tone.
const COV_STATUS_KEYS: Record<string, string> = {
  mastered: 'covMastered',
  practiced: 'covPracticed',
  taught: 'covTaught',
  uncovered: 'covUncovered',
}
const COV_STATUS_TONES: Record<string, 'default' | 'ok' | 'warn' | 'teal'> = {
  mastered: 'ok',
  practiced: 'teal',
  uncovered: 'warn',
}
const covLabel = (status: string): string =>
  COV_STATUS_KEYS[status] ? t(COV_STATUS_KEYS[status] as Parameters<typeof t>[0]) : status

export default function TeacherDashboard() {
  // S2.2: classrooms replace the bare class-number input.
  const [rooms, setRooms] = useState<ClassRoom[]>([])
  const [roomId, setRoomId] = useState<number | null>(null)
  const [roster, setRoster] = useState<RosterEntry[]>([])
  const [analytics, setAnalytics] = useState<ClassAnalytics | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [newLevel, setNewLevel] = useState(6)
  const [newSection, setNewSection] = useState('GEN')
  const [createBusy, setCreateBusy] = useState(false)

  const [csvText, setCsvText] = useState('')
  const [importBusy, setImportBusy] = useState(false)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)

  // C16: assign a quiz to a specific student straight from the roster.
  const [assignTo, setAssignTo] = useState<number | null>(null)
  const [assignSubject, setAssignSubject] = useState('science')
  const [assignCount, setAssignCount] = useState(5)
  const [assignBusy, setAssignBusy] = useState(false)
  const [assignMsg, setAssignMsg] = useState<string | null>(null)

  // S2.4: question paper builder (AI draft -> review every question -> FINAL).
  const [qpLevel, setQpLevel] = useState(6)
  const [qpSubject, setQpSubject] = useState('science')
  const [qpExamType, setQpExamType] = useState('')
  const [qpChapters, setQpChapters] = useState('')
  const [qpMarks, setQpMarks] = useState(10)
  const [qpDuration, setQpDuration] = useState(10)
  const [qpEasy, setQpEasy] = useState(30)
  const [qpMedium, setQpMedium] = useState(50)
  const [qpHard, setQpHard] = useState(20)
  const [qpBusy, setQpBusy] = useState(false)
  const [qpMsg, setQpMsg] = useState<string | null>(null)
  const [qp, setQp] = useState<QPaper | null>(null)
  const [qpEdits, setQpEdits] = useState<Record<string, string>>({})

  // S2.5: short tests -- one click assigns a chapter test to the whole class.
  const [stChapter, setStChapter] = useState('')
  const [stSubject, setStSubject] = useState('science')
  const [stNum, setStNum] = useState(5)
  const [stDuration, setStDuration] = useState(10)
  const [stBusy, setStBusy] = useState(false)
  const [stMsg, setStMsg] = useState<string | null>(null)
  const [stTests, setStTests] = useState<ShortTest[]>([])

  // S2.6: lesson plan copilot -- one AI call, eight editable printable sections.
  const [lpChapter, setLpChapter] = useState('')
  const [lpSubject, setLpSubject] = useState('science')
  const [lpMinutes, setLpMinutes] = useState(35)
  const [lpLevel, setLpLevel] = useState('average')
  const [lpBusy, setLpBusy] = useState(false)
  const [lpMsg, setLpMsg] = useState<string | null>(null)
  const [lp, setLp] = useState<LessonPlan | null>(null)
  const [lpEdits, setLpEdits] = useState<Record<string, string>>({})

  // S2.7: weakness heatmap + rule-based at-risk support plans.
  const [wm, setWm] = useState<WeakMatrix | null>(null)
  const [sps, setSps] = useState<SupportPlanRow[]>([])
  const [spBusy, setSpBusy] = useState(false)
  const [spMsg, setSpMsg] = useState<string | null>(null)

  // S2.8: bulk assignment -- roster multi-select, one quiz, due date, tracking.
  const [selIds, setSelIds] = useState<Set<number>>(new Set())
  const [asChapter, setAsChapter] = useState('')
  const [asSubject, setAsSubject] = useState('science')
  const [asCount, setAsCount] = useState(5)
  const [asDue, setAsDue] = useState('')
  const [asBusy, setAsBusy] = useState(false)
  const [asMsg, setAsMsg] = useState<string | null>(null)
  const [assigns, setAssigns] = useState<AssignmentRow[]>([])
  const [asProg, setAsProg] = useState<Record<number, AssignmentProgressRow[]>>({})
  const [asOpen, setAsOpen] = useState<number | null>(null)

  // S3.3: class x subject curriculum coverage grid (school-wide, once).
  const [cov, setCov] = useState<Coverage | null>(null)

  const selected = rooms.find((r) => r.id === roomId) ?? null

  const loadRooms = useCallback(() => {
    get<ClassRoom[]>('/teacher/classrooms')
      .then((rs) => {
        setRooms(rs)
        setRoomId((cur) => (cur !== null && rs.some((r) => r.id === cur) ? cur : rs[0]?.id ?? null))
      })
      .catch((err: unknown) => setError(errText(err)))
  }, [])

  useEffect(() => {
    loadRooms()
  }, [loadRooms])

  const load = useCallback(() => {
    if (roomId === null) {
      setRoster([])
      setAnalytics(null)
      setWm(null)
      setSps([])
      setSelIds(new Set())
      return
    }
    setError(null)
    Promise.all([
      get<RosterEntry[]>(`/teacher/classrooms/${roomId}/roster`),
      selected ? get<ClassAnalytics>(`/teacher/classes/${selected.class_level}/analytics`) : Promise.resolve(null),
      // S2.7: heatmap + plans ride the same room switch; auxiliary on failure.
      selected
        ? get<WeakMatrix>(`/teacher/weak-matrix?class_level=${selected.class_level}`).catch(
            () => null,
          )
        : Promise.resolve(null),
      get<SupportPlanRow[]>('/teacher/support-plans').catch(() => []),
      // S2.8: bulk assignments + their completion caches refresh too.
      get<AssignmentRow[]>('/teacher/assignments').catch(() => []),
    ])
      .then(([r, a, m, plans, rows]) => {
        setRoster(r)
        setAnalytics(a)
        setWm(m ?? null)
        setSps(plans ?? [])
        setAssigns(rows ?? [])
        setAsProg({})
        setAsOpen(null)
        setSelIds(new Set())
      })
      .catch((err: unknown) => setError(errText(err)))
  }, [roomId, selected])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    let live = true
    get<Coverage>('/teacher/curriculum-coverage')
      .then((c) => {
        if (live) setCov(c)
      })
      .catch(() => {
        if (live) setCov(null)
      })
    return () => {
      live = false
    }
  }, [])

  async function createRoom(e: React.FormEvent) {
    e.preventDefault()
    if (createBusy) return
    setCreateBusy(true)
    setError(null)
    try {
      const room = await post<ClassRoom>('/teacher/classrooms', {
        class_level: newLevel,
        section: newSection || 'GEN',
      })
      setRooms((rs) => [...rs, room].sort((a, b) => a.class_level - b.class_level || a.section.localeCompare(b.section)))
      setRoomId(room.id)
    } catch (err) {
      setError(errText(err))
    } finally {
      setCreateBusy(false)
    }
  }

  async function runImport(e: React.FormEvent) {
    e.preventDefault()
    if (roomId === null || importBusy || !csvText.trim()) return
    setImportBusy(true)
    setImportResult(null)
    try {
      const res = await post<ImportResult>(`/teacher/classrooms/${roomId}/import`, {
        csv_text: csvText,
      })
      setImportResult(res)
      setCsvText('')
      load()
      loadRooms()
    } catch (err) {
      setError(errText(err))
    } finally {
      setImportBusy(false)
    }
  }

  async function assignQuiz(e: React.FormEvent) {
    e.preventDefault()
    if (assignTo === null || assignBusy || selected === null) return
    setAssignBusy(true)
    setAssignMsg(null)
    try {
      const started = await post<{ attempt_id: number }>('/quizzes', {
        student_id: assignTo,
        class_level: selected.class_level,
        subject: assignSubject,
        num_questions: assignCount,
      })
      setAssignMsg(t('assigned', { id: started.attempt_id }))
    } catch (err) {
      setAssignMsg(errText(err))
    } finally {
      setAssignBusy(false)
    }
  }

  // --- S2.4 question paper handlers -------------------------------------
  const qpAllReviewed =
    qp !== null && qp.questions.length > 0 && qp.questions.every((q) => q.reviewed)

  async function runQp<T>(fn: () => Promise<T>): Promise<T | null> {
    setQpBusy(true)
    setQpMsg(null)
    try {
      return await fn()
    } catch (err) {
      setQpMsg(errText(err))
      return null
    } finally {
      setQpBusy(false)
    }
  }

  async function generateQp(e: React.FormEvent) {
    e.preventDefault()
    const chapters = qpChapters.split(',').map((c) => c.trim()).filter(Boolean)
    const res = await runQp(() =>
      post<QPaper>('/teacher/qpapers', {
        class_level: qpLevel,
        subject: qpSubject,
        chapters,
        exam_type: qpExamType,
        marks: qpMarks,
        duration_min: qpDuration,
        difficulty: { easy: qpEasy, medium: qpMedium, hard: qpHard },
      }),
    )
    if (res) {
      setQp(res)
      setQpEdits({})
      setQpMsg(t('qpDraftReady'))
    }
  }

  async function qpRegenerate() {
    if (!qp) return
    const res = await runQp(() => post<QPaper>(`/teacher/qpapers/${qp.id}/regenerate`))
    if (res) {
      setQp(res)
      setQpEdits({})
    }
  }

  async function qpShuffle() {
    if (!qp) return
    const res = await runQp(() => post<QPaper>(`/teacher/qpapers/${qp.id}/shuffle`))
    if (res) setQp(res)
  }

  async function qpReview(refs?: string[]) {
    if (!qp) return
    const list = refs ? qp.questions.filter((q) => refs.includes(q.ref)) : qp.questions
    const decisions = list.map((q) => {
      const edit = (qpEdits[q.ref] ?? '').trim()
      return edit ? { ref: q.ref, action: 'edit' as const, text: edit } : { ref: q.ref, action: 'accept' as const }
    })
    const res = await runQp(() =>
      post<QPaper>(`/teacher/qpapers/${qp.id}/review`, { decisions }),
    )
    if (res) {
      setQp(res)
      setQpEdits({})
    }
  }

  async function qpReplace(ref: string) {
    if (!qp) return
    const res = await runQp(() => post<QPaper>(`/teacher/qpapers/${qp.id}/replace`, { ref }))
    if (res) setQp(res)
  }

  async function qpFinalize() {
    if (!qp) return
    const res = await runQp(() => post<QPaper>(`/teacher/qpapers/${qp.id}/finalize`))
    if (res) {
      setQp(res)
      setQpMsg(t('qpFinalized'))
    }
  }

  async function qpDownload(kind: string) {
    if (!qp) return
    try {
      const res = await fetch(`${apiBase}/teacher/qpapers/${qp.id}/pdf?kind=${kind}`, {
        headers: { Authorization: `Bearer ${getToken() ?? ''}` },
      })
      if (!res.ok) throw new Error(String(res.status))
      const url = URL.createObjectURL(await res.blob())
      const a = document.createElement('a')
      a.href = url
      a.download = `qp-${qp.id}-${kind}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setQpMsg(t('errorGeneric'))
    }
  }

  // --- S2.5 short test handlers --------------------------------------------
  useEffect(() => {
    get<ShortTest[]>('/teacher/shorttests')
      .then((rows) => setStTests(rows ?? []))
      .catch(() => {
        /* list is auxiliary; assignment surfaces its own errors */
      })
  }, [roomId])

  async function assignShortTest(e: React.FormEvent) {
    e.preventDefault()
    if (roomId === null || stBusy || !stChapter.trim()) return
    setStBusy(true)
    setStMsg(null)
    try {
      const st = await post<ShortTest>('/teacher/shorttests', {
        classroom_id: roomId,
        subject: stSubject,
        chapter: stChapter.trim(),
        num_questions: stNum,
        duration_min: stDuration,
      })
      setStTests((ls) => [st, ...ls])
      setStMsg(t('stAssigned', { n: st.attempts.length }))
    } catch (err) {
      setStMsg(errText(err))
    } finally {
      setStBusy(false)
    }
  }

  // --- S2.6 lesson plan copilot handler --------------------------------------
  async function generateLessonPlan(e: React.FormEvent) {
    e.preventDefault()
    if (selected === null || lpBusy || !lpChapter.trim()) return
    setLpBusy(true)
    setLpMsg(null)
    try {
      const plan = await post<LessonPlan>('/teacher/lesson-plans', {
        class_level: selected.class_level,
        subject: lpSubject,
        chapter: lpChapter.trim(),
        minutes: lpMinutes,
        level: lpLevel,
      })
      setLp(plan)
      setLpEdits({})
    } catch (err) {
      setLpMsg(errText(err))
    } finally {
      setLpBusy(false)
    }
  }

  // --- S2.7 support plan handler ---------------------------------------------
  async function createSupportPlan(studentId: number) {
    if (spBusy) return
    setSpBusy(true)
    setSpMsg(null)
    try {
      const row = await post<SupportPlanRow>('/teacher/support-plans', {
        student_id: studentId,
      })
      setSps((ls) => [row, ...ls])
    } catch (err) {
      setSpMsg(errText(err))
    } finally {
      setSpBusy(false)
    }
  }

  // --- S2.8 bulk assignment handlers ------------------------------------------
  function toggleSel(id: number) {
    setSelIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const allSelected = roster.length > 0 && roster.every((s) => selIds.has(s.student_id))

  function toggleAllSel() {
    setSelIds(allSelected ? new Set() : new Set(roster.map((s) => s.student_id)))
  }

  async function assignBulk(e: React.FormEvent) {
    e.preventDefault()
    if (asBusy || selIds.size === 0 || !asChapter.trim() || !asDue) return
    setAsBusy(true)
    setAsMsg(null)
    try {
      const row = await post<AssignmentRow>('/teacher/assignments', {
        student_ids: [...selIds],
        subject: asSubject,
        chapter: asChapter.trim(),
        num_questions: asCount,
        due_at: asDue,
      })
      setAssigns((ls) => [row, ...ls])
      setSelIds(new Set())
      setAsMsg(t('baSelected', { n: row.attempts.length }))
    } catch (err) {
      setAsMsg(errText(err))
    } finally {
      setAsBusy(false)
    }
  }

  async function toggleProgress(id: number) {
    if (asOpen === id) {
      setAsOpen(null)
      return
    }
    setAsOpen(id)
    if (asProg[id]) return
    try {
      const rows = await get<AssignmentProgressRow[]>(`/teacher/assignments/${id}/progress`)
      setAsProg((m) => ({ ...m, [id]: rows }))
    } catch (err) {
      setAsMsg(errText(err))
    }
  }

  return (
    <>
      <h1 className="page-title">{t('teacherDashboard')}</h1>

      <CreateHub />

      <div className="card">
        <div className="row-flex" style={{ gap: '8px', flexWrap: 'wrap' }}>
          {rooms.map((r) => (
            <button
              key={r.id}
              className={`chip${r.id === roomId ? ' active' : ''}`}
              aria-pressed={r.id === roomId}
              onClick={() => setRoomId(r.id)}
            >
              {t('className').replace(/\s*\(.*\)/, '')} {r.class_level} · {r.section} ({r.student_count})
            </button>
          ))}
          {rooms.length === 0 && <p className="muted">{t('noStudents')}</p>}
          <button className="btn-ghost btn-sm" onClick={loadRooms}>
            {t('refreshBtn')}
          </button>
        </div>
        <form onSubmit={createRoom} className="row-flex" style={{ gap: '8px', marginTop: '8px' }}>
          <label htmlFor="ncls">{t('newClassroom')}</label>
          <select
            id="ncls"
            value={newLevel}
            onChange={(e) => setNewLevel(Number(e.target.value))}
          >
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <input
            id="nsec"
            value={newSection}
            maxLength={8}
            style={{ width: '90px' }}
            aria-label={t('section')}
            onChange={(e) => setNewSection(e.target.value)}
          />
          <button className="small secondary" type="submit" disabled={createBusy}>
            {t('newClassroom')}
          </button>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
      </div>

      {selected && (
        <div className="card">
          <h2>{t('csvImport')}</h2>
          <p className="muted">{t('csvHint')}</p>
          <form onSubmit={runImport}>
            <textarea
              rows={5}
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
              placeholder={'name,email'}
              style={{ width: '100%', fontFamily: 'monospace' }}
            />
            <button className="primary" type="submit" disabled={importBusy || !csvText.trim()}>
              {importBusy ? <span className="spinner" aria-hidden /> : t('importBtn')}
            </button>
          </form>
          {importResult && (
            <div role="status">
              <p>
                <span>{t('importCreated', { n: importResult.created })}</span>
                {' · '}
                <span>{t('importFailed', { n: importResult.failed })}</span>
              </p>
              {importResult.rows.some((r) => r.invite_code) && (
                <div className="table-scroll">
                  <table>
                    <tbody>
                      {importResult.rows
                        .filter((r) => r.invite_code)
                        .map((r) => (
                          <tr key={r.email}>
                            <td>{r.name}</td>
                            <td>{r.email}</td>
                            <td>
                              {t('inviteCode')}: <code>{r.invite_code}</code>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}

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
                  <th scope="col">
                    {/* S2.8: select-all rides the bulk-assign flow. */}
                    <input
                      type="checkbox"
                      aria-label={t('baSelect')}
                      checked={allSelected}
                      onChange={toggleAllSel}
                    />
                  </th>
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
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${t('baSelect')}: ${s.name}`}
                        checked={selIds.has(s.student_id)}
                        onChange={() => toggleSel(s.student_id)}
                      />
                    </td>
                    <td>{s.student_id}</td>
                    <td>
                      {s.name}
                      {s.email && <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{s.email}</div>}
                      {s.invite_pending && <span className="badge"> {t('invitePending')}</span>}
                    </td>
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

      {/* S2.8: bulk assign -- selected students share one quiz and a due date. */}
      <div className="card">
        <h2>{t('baTitle')}</h2>
        <form onSubmit={assignBulk} className="row-flex" style={{ gap: '8px', flexWrap: 'wrap' }}>
          <label htmlFor="bachap">{t('baChapterLabel')}</label>
          <input
            id="bachap"
            value={asChapter}
            onChange={(e) => setAsChapter(e.target.value)}
            style={{ minWidth: '140px' }}
          />
          <label htmlFor="basubj">{t('subject')}</label>
          <select id="basubj" value={asSubject} onChange={(e) => setAsSubject(e.target.value)}>
            <option value="science">{t('subjectScience')}</option>
            <option value="math">{t('subjectMath')}</option>
            <option value="bangla">{t('subjectBangla')}</option>
          </select>
          <label htmlFor="bacount">{t('questionCount')}</label>
          <input
            id="bacount"
            type="number"
            min={3}
            max={25}
            value={asCount}
            onChange={(e) => setAsCount(Number(e.target.value) || 5)}
            style={{ width: '64px' }}
          />
          <label htmlFor="badue">{t('baDue')}</label>
          <input id="badue" type="datetime-local" value={asDue} onChange={(e) => setAsDue(e.target.value)} />
          <button
            className="primary"
            disabled={asBusy || selIds.size === 0 || !asChapter.trim() || !asDue}
          >
            {t('baAssign')} ({t('baSelected', { n: selIds.size })})
          </button>
        </form>
        {asMsg && <p className="muted">{asMsg}</p>}
        {assigns.length === 0 ? (
          <p className="muted">{t('baNone')}</p>
        ) : (
          <ul>
            {assigns.slice(0, 8).map((a) => (
              <li key={a.id} style={{ marginBottom: 'var(--space-3)' }}>
                <strong>{a.chapter}</strong> · {a.subject} ·{' '}
                {t('baSelected', { n: a.attempts.length })} · {t('baDue')}:{' '}
                {new Date(a.due_at).toLocaleString()}
                <button className="small secondary" onClick={() => toggleProgress(a.id)}>
                  {t('baProgress')}
                </button>
                {asOpen === a.id && asProg[a.id] && (
                  <table className="data" style={{ marginTop: 'var(--space-2)' }}>
                    <thead>
                      <tr>
                        <th scope="col">{t('name')}</th>
                        <th scope="col">{t('baStatus')}</th>
                        <th scope="col">{t('avgScore')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {asProg[a.id].map((r) => (
                        <tr key={r.attempt_id}>
                          <td>{r.name}</td>
                          <td>
                            {r.done ? (
                              <span className="badge badge-ok"> {t('baDone')}</span>
                            ) : r.overdue ? (
                              <span className="badge badge-warn"> {t('baOverdue')}</span>
                            ) : (
                              <span className="badge"> {t('baPending')}</span>
                            )}
                          </td>
                          <td>{r.score_pct === null ? '·' : `${Math.round(r.score_pct)}%`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {assignTo !== null && (
        <div className="card">
          <h3>
            {t('assignQuiz')} &middot; #{assignTo}
          </h3>
          <form onSubmit={assignQuiz} className="grid-2">
            <div>
              <label htmlFor="asubj">{t('subject')}</label>
              <select id="asubj" value={assignSubject} onChange={(e) => setAssignSubject(e.target.value)}>
                <option value="science">{t('subjectScience')}</option>
                <option value="math">{t('subjectMath')}</option>
                <option value="bangla">{t('subjectBangla')}</option>
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

      <div className="card">
        <h2>{t('qpTitle')}</h2>
        <form onSubmit={generateQp} className="grid-2">
          <div>
            <label htmlFor="qpexam">{t('qpExamType')}</label>
            <input
              id="qpexam"
              value={qpExamType}
              maxLength={40}
              onChange={(e) => setQpExamType(e.target.value)}
            />
            <label htmlFor="qplvl">{t('className').replace(/\s*\(.*\)/, '')}</label>
            <select id="qplvl" value={qpLevel} onChange={(e) => setQpLevel(Number(e.target.value))}>
              {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            <label htmlFor="qpsubj">{t('subject')}</label>
            <select id="qpsubj" value={qpSubject} onChange={(e) => setQpSubject(e.target.value)}>
              <option value="science">{t('subjectScience')}</option>
              <option value="math">{t('subjectMath')}</option>
              <option value="bangla">{t('subjectBangla')}</option>
            </select>
          </div>
          <div>
            <label htmlFor="qpchapters">{t('chapter')}</label>
            <input
              id="qpchapters"
              value={qpChapters}
              onChange={(e) => setQpChapters(e.target.value)}
            />
            <div className="row-flex" style={{ gap: '8px' }}>
              <div style={{ flex: 1 }}>
                <label htmlFor="qpmarks">{t('qpMarks')}</label>
                <input
                  id="qpmarks"
                  type="number"
                  min={5}
                  max={100}
                  value={qpMarks}
                  onChange={(e) => setQpMarks(Number(e.target.value))}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label htmlFor="qpdur">{t('qpDuration')}</label>
                <input
                  id="qpdur"
                  type="number"
                  min={5}
                  max={300}
                  value={qpDuration}
                  onChange={(e) => setQpDuration(Number(e.target.value))}
                />
              </div>
            </div>
            <div className="row-flex" style={{ gap: '8px' }}>
              <div style={{ flex: 1 }}>
                <label htmlFor="qpeasy">{t('qpEasy')}</label>
                <input
                  id="qpeasy"
                  type="number"
                  min={0}
                  max={100}
                  value={qpEasy}
                  onChange={(e) => setQpEasy(Number(e.target.value))}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label htmlFor="qpmedium">{t('qpMedium')}</label>
                <input
                  id="qpmedium"
                  type="number"
                  min={0}
                  max={100}
                  value={qpMedium}
                  onChange={(e) => setQpMedium(Number(e.target.value))}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label htmlFor="qphard">{t('qpHard')}</label>
                <input
                  id="qphard"
                  type="number"
                  min={0}
                  max={100}
                  value={qpHard}
                  onChange={(e) => setQpHard(Number(e.target.value))}
                />
              </div>
            </div>
            <button
              className="primary"
              type="submit"
              disabled={qpBusy || !qpExamType.trim() || !qpChapters.trim()}
            >
              {qpBusy ? <span className="spinner" aria-hidden /> : t('qpGenerate')}
            </button>
          </div>
        </form>
        {qpMsg && (
          <p role="status" className={qpMsg === t('errorGeneric') ? 'error' : undefined}>
            {qpMsg}
          </p>
        )}
        {qp && (
          <div>
            <p role="status" className="muted">
              {qp.status === 'final' ? t('qpFinalized') : qpAllReviewed ? t('qpDraftReady') : t('qpNeedsReview')}
            </p>
            <ol>
              {qp.questions.map((q, idx) => (
                <li key={q.ref} style={{ marginBottom: '12px' }}>
                  <p>
                    {q.text} <span className="muted">[{q.difficulty}]</span>
                    {q.reviewed && <span className="badge"> {t('qpReviewAll')}</span>}
                  </p>
                  <ul style={{ margin: '4px 0' }}>
                    {q.options.map((o, oi) => (
                      <li key={oi} style={oi === q.answer_index ? { fontWeight: 700 } : undefined}>
                        {o}
                      </li>
                    ))}
                  </ul>
                  {qp.status !== 'final' && (
                    <div className="row-flex" style={{ gap: '8px' }}>
                      <input
                        aria-label={`${t('qpTitle')} ${idx + 1}`}
                        placeholder={q.text}
                        value={qpEdits[q.ref] ?? ''}
                        onChange={(e) => setQpEdits((ed) => ({ ...ed, [q.ref]: e.target.value }))}
                        style={{ flex: 1 }}
                      />
                      <button className="small secondary" disabled={qpBusy} onClick={() => qpReview([q.ref])}>
                        {t('qpReviewAll')}
                      </button>
                      <button className="small secondary" disabled={qpBusy} onClick={() => qpReplace(q.ref)}>
                        {t('qpReplace')}
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ol>
            {qp.status !== 'final' && (
              <div className="row-flex" style={{ gap: '8px', flexWrap: 'wrap' }}>
                <button className="small secondary" disabled={qpBusy} onClick={() => qpReview()}>
                  {t('qpReviewAll')}
                </button>
                <button className="small secondary" disabled={qpBusy} onClick={qpRegenerate}>
                  {t('qpRegenerate')}
                </button>
                <button className="small secondary" disabled={qpBusy} onClick={qpShuffle}>
                  {t('qpShuffle')}
                </button>
                <button className="primary" disabled={qpBusy || !qpAllReviewed} onClick={qpFinalize}>
                  {t('qpFinalize')}
                </button>
              </div>
            )}
            <div className="row-flex" style={{ gap: '8px', marginTop: '8px' }}>
              <button className="btn-ghost btn-sm" disabled={qpBusy} onClick={() => qpDownload('paper')}>
                PDF
              </button>
              <button className="btn-ghost btn-sm" disabled={qpBusy} onClick={() => qpDownload('answer')}>
                PDF+
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h2>{t('stTitle')}</h2>
        <form onSubmit={assignShortTest} className="row-flex" style={{ gap: '8px', flexWrap: 'wrap' }}>
          <label htmlFor="stchap">{t('stChapterLabel')}</label>
          <input
            id="stchap"
            value={stChapter}
            onChange={(e) => setStChapter(e.target.value)}
            style={{ minWidth: '140px' }}
          />
          <label htmlFor="stsubj">{t('subject')}</label>
          <select id="stsubj" value={stSubject} onChange={(e) => setStSubject(e.target.value)}>
            <option value="science">{t('subjectScience')}</option>
            <option value="math">{t('subjectMath')}</option>
            <option value="bangla">{t('subjectBangla')}</option>
          </select>
          <label htmlFor="stnum">{t('questionCount')}</label>
          <input
            id="stnum"
            type="number"
            min={1}
            max={10}
            value={stNum}
            onChange={(e) => setStNum(Number(e.target.value) || 1)}
            style={{ width: '64px' }}
          />
          <label htmlFor="stdur">{t('qpDuration')}</label>
          <input
            id="stdur"
            type="number"
            min={1}
            max={60}
            value={stDuration}
            onChange={(e) => setStDuration(Number(e.target.value) || 1)}
            style={{ width: '64px' }}
          />
          <button className="primary" disabled={stBusy || roomId === null || !stChapter.trim()}>
            {t('stAssign')}
          </button>
        </form>
        {stMsg && <p className="muted">{stMsg}</p>}
        {stTests.length === 0 ? (
          <p className="muted">{t('stEmpty')}</p>
        ) : (
          <ul>
            {stTests.slice(0, 5).map((st) => (
              <li key={st.id}>
                {st.chapter} · {st.subject} · {st.questions.length}Q · {t('stAssigned', { n: st.attempts.length })}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <h2>{t('lpTitle')}</h2>
        <form onSubmit={generateLessonPlan} className="row-flex" style={{ gap: '8px', flexWrap: 'wrap' }}>
          <label htmlFor="lpchap">{t('lpChapterLabel')}</label>
          <input
            id="lpchap"
            value={lpChapter}
            onChange={(e) => setLpChapter(e.target.value)}
            style={{ minWidth: '140px' }}
          />
          <label htmlFor="lpsubj">{t('subject')}</label>
          <select id="lpsubj" value={lpSubject} onChange={(e) => setLpSubject(e.target.value)}>
            <option value="science">{t('subjectScience')}</option>
            <option value="math">{t('subjectMath')}</option>
            <option value="bangla">{t('subjectBangla')}</option>
          </select>
          <label htmlFor="lpmmin">{t('lpMinutesLabel')}</label>
          <input
            id="lpmmin"
            type="number"
            min={5}
            max={180}
            value={lpMinutes}
            onChange={(e) => setLpMinutes(Number(e.target.value) || 5)}
            style={{ width: '72px' }}
          />
          <label htmlFor="lplevel">{t('lpLevelLabel')}</label>
          <select id="lplevel" value={lpLevel} onChange={(e) => setLpLevel(e.target.value)}>
            <option value="beginner">{t('lpLevelBeginner')}</option>
            <option value="average">{t('lpLevelAverage')}</option>
            <option value="advanced">{t('lpLevelAdvanced')}</option>
          </select>
          <button className="primary" disabled={lpBusy || selected === null || !lpChapter.trim()}>
            {t('lpGenerate')}
          </button>
        </form>
        {lpMsg && <p className="muted">{lpMsg}</p>}
        {lp && (
          <div className="lesson-print">
            <p className="muted">
              {lp.chapter} · {lp.subject} · {lp.class_level} · {t('stMinutes', { n: lp.minutes })} ·{' '}
              {lp.level === 'beginner'
                ? t('lpLevelBeginner')
                : lp.level === 'advanced'
                  ? t('lpLevelAdvanced')
                  : t('lpLevelAverage')}
            </p>
            {Object.entries(lp.sections).map(([key, value]) => (
              <div key={key} style={{ marginBottom: '8px' }}>
                <label htmlFor={`lpsec-${key}`}>
                  {t((LESSON_SECTION_LABELS[key] ?? 'lpTitle') as Parameters<typeof t>[0])}
                </label>
                <textarea
                  id={`lpsec-${key}`}
                  value={lpEdits[key] ?? value}
                  onChange={(e) => setLpEdits((m) => ({ ...m, [key]: e.target.value }))}
                  rows={3}
                  style={{ width: '100%' }}
                />
              </div>
            ))}
            <button
              type="button"
              className="lp-no-print"
              onClick={() => window.print()}
            >
              {t('lpPrint')}
            </button>
          </div>
        )}
      </div>

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

      {/* S2.7: concept x student weakness heatmap with at-risk support plans. */}
      <div className="card">
        <h2>{t('wmTitle')}</h2>
        {wm === null || wm.concepts.length === 0 ? (
          <p className="muted">{t('wmEmpty')}</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">{t('wmConcept')}</th>
                  {wm.students.map((s) => (
                    <th key={s.student_id} scope="col">
                      {s.name}
                      {s.at_risk && <span className="badge badge-warn"> {t('spRisk')}</span>}
                      {(s.weak_concepts ?? []).length > 0 && (
                        <div
                          className="wm-weak-chips"
                          style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '4px' }}
                        >
                          {(s.weak_concepts ?? []).slice(0, 3).map((c) => (
                            <span key={c} className="badge">
                              {c}
                            </span>
                          ))}
                        </div>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {wm.concepts.map((ch) => (
                  <tr key={ch}>
                    <th scope="row">{ch}</th>
                    {wm.students.map((s) => {
                      const c = s.cells[ch]
                      return (
                        <td
                          key={s.student_id}
                          className={`wm-cell ${heatClass(c ? c.accuracy : null)}`}
                          title={c && c.read ? t('wmRead') : undefined}
                        >
                          {c && c.accuracy !== null ? `${Math.round(c.accuracy)}%` : '·'}
                        </td>
                      )
                    })}
                  </tr>
                ))}
                <tr>
                  <th scope="row">
                    {t('wmAvg')} / {t('wmTrend')}
                  </th>
                  {wm.students.map((s) => (
                    <td key={s.student_id} className="wm-cell">
                      {s.avg_score_pct !== null ? `${Math.round(s.avg_score_pct)}%` : '·'}{' '}
                      {s.trend === 'down' ? '▼' : s.trend === 'up' ? '▲' : '–'}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        )}
        {wm !== null && wm.students.some((s) => s.at_risk) && (
          <div className="row-flex" style={{ gap: '8px', flexWrap: 'wrap', marginTop: '8px' }}>
            {wm.students
              .filter((s) => s.at_risk)
              .map((s) => (
                <button
                  key={s.student_id}
                  disabled={spBusy}
                  onClick={() => createSupportPlan(s.student_id)}
                >
                  {s.name}: {t('spCreate')}
                </button>
              ))}
          </div>
        )}
        {spMsg && <p className="muted">{spMsg}</p>}
        <h3 style={{ marginTop: 'var(--space-4)' }}>{t('spTitle')}</h3>
        {sps.length === 0 ? (
          <p className="muted">{t('spEmpty')}</p>
        ) : (
          <ul>
            {sps.map((p) => (
              <li key={p.id} style={{ marginBottom: 'var(--space-3)' }}>
                <strong>
                  {wm?.students.find((x) => x.student_id === p.student_id)?.name ??
                    `#${p.student_id}`}
                </strong>
                {(p.plan.weeks ?? []).map((w) => (
                  <div key={w.week} className="muted">
                    {t('spWeek', { n: w.week })} — {stageLabel(w.stage)}
                    {w.detail ? ` (${w.detail})` : ''}
                  </div>
                ))}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* S3.3: class x subject curriculum coverage grid. */}
      <div className="card">
        <h2>{t('covTitle')}</h2>
        {cov === null || cov.cells.length === 0 ? (
          <p className="muted">{t('covEmpty')}</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">{t('classLabel')}</th>
                  {cov.subjects.map((s) => (
                    <th key={s} scope="col">
                      {s}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from(new Map(cov.cells.map((c) => [c.classroom_id, c])).values()).map(
                  (roomCell) => (
                    <tr key={roomCell.classroom_id}>
                      <th scope="row">{`${roomCell.class_level} · ${roomCell.section}`}</th>
                      {cov.subjects.map((s) => {
                        const c = cov.cells.find(
                          (x) => x.classroom_id === roomCell.classroom_id && x.subject === s,
                        )
                        return (
                          <td key={s}>
                            {c ? (
                              <Badge tone={COV_STATUS_TONES[c.status] ?? 'default'}>
                                {covLabel(c.status)}
                              </Badge>
                            ) : (
                              '·'
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
