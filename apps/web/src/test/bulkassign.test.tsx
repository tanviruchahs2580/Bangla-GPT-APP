import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TeacherDashboard from '../pages/TeacherDashboard'
import { t } from '../i18n'
import type { AssignmentProgressRow, AssignmentRow } from '../types'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  ...apiMock,
  apiBase: '/api',
  getToken: () => 'tok',
}))

const ROOMS = [{ id: 1, class_level: 6, section: 'GEN', student_count: 2 }]

const ROSTER = [
  {
    student_id: 11,
    name: 'Rahim',
    class_level: 6,
    email: 'rahim@school.edu',
    invite_pending: false,
    attempts_graded: 1,
    avg_score_pct: 60,
  },
  {
    student_id: 12,
    name: 'Karim',
    class_level: 6,
    email: null,
    invite_pending: false,
    attempts_graded: 1,
    avg_score_pct: 40,
  },
]

const EMPTY_ANALYTICS = {
  class_level: 6,
  students: 2,
  chapters: [],
  weak_chapters: [],
  students_detail: [],
}

const NEW_ASSIGNMENT: AssignmentRow = {
  id: 5,
  teacher_id: 3,
  subject: 'science',
  chapter: 'kosh',
  num_questions: 5,
  due_at: '2026-09-10T10:00:00',
  questions: [{ id: 'q1', question_text: 'Q one', options: ['a', 'b', 'c', 'd'] }],
  attempts: [
    { student_id: 11, attempt_id: 21 },
    { student_id: 12, attempt_id: 22 },
  ],
  created_at: '2026-09-03T09:00:00',
}

const PROGRESS: AssignmentProgressRow[] = [
  { student_id: 11, name: 'Rahim', attempt_id: 21, done: true, score_pct: 80, overdue: false },
  { student_id: 12, name: 'Karim', attempt_id: 22, done: false, score_pct: null, overdue: false },
]

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.get.mockImplementation((path: string) => {
    if (path === '/teacher/classrooms') return Promise.resolve(structuredClone(ROOMS))
    if (path.endsWith('/roster')) return Promise.resolve(structuredClone(ROSTER))
    if (path === '/teacher/assignments') return Promise.resolve([])
    if (path.startsWith('/teacher/assignments/')) return Promise.resolve(structuredClone(PROGRESS))
    if (path.includes('/analytics')) return Promise.resolve(structuredClone(EMPTY_ANALYTICS))
    return Promise.resolve(null)
  })
  apiMock.post.mockImplementation((path: string) => {
    if (path === '/teacher/assignments') return Promise.resolve(structuredClone(NEW_ASSIGNMENT))
    return Promise.resolve(null)
  })
})

describe('S2.8 bulk assign card', () => {
  it('multi-selects students, assigns one quiz with a due date', async () => {
    const user = userEvent.setup()
    render(<TeacherDashboard />)
    await screen.findByText('Rahim')

    expect(screen.getByText(t('baNone'))).toBeInTheDocument()

    const assignBtn = screen.getByRole('button', { name: new RegExp(t('baAssign')) })
    expect(assignBtn).toBeDisabled() // nobody selected yet

    await user.click(screen.getByLabelText(`${t('baSelect')}: Rahim`))
    await user.click(screen.getByLabelText(`${t('baSelect')}: Karim`))
    await user.type(screen.getByLabelText(t('baChapterLabel')), 'kosh')
    // still blocked until a due date is set
    expect(assignBtn).toBeDisabled()
    fireEvent.change(screen.getByLabelText(t('baDue')), { target: { value: '2026-09-10T10:00' } })
    expect(assignBtn).toBeEnabled()
    await user.click(assignBtn)

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith('/teacher/assignments', {
        student_ids: [11, 12],
        subject: 'science',
        chapter: 'kosh',
        num_questions: 5,
        due_at: '2026-09-10T10:00',
      }),
    )
    // the assignment shows up; selections reset so the button disables again
    expect(await screen.findByText(/kosh/)).toBeInTheDocument()
    expect(screen.queryByText(t('baNone'))).not.toBeInTheDocument()
    expect(assignBtn).toBeDisabled()
    expect(screen.getByLabelText(`${t('baSelect')}: Rahim`)).not.toBeChecked()
  })

  it('shows the per-student completion list', async () => {
    const user = userEvent.setup()
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/teacher/classrooms') return Promise.resolve(structuredClone(ROOMS))
      if (path.endsWith('/roster')) return Promise.resolve(structuredClone(ROSTER))
      if (path === '/teacher/assignments') return Promise.resolve([structuredClone(NEW_ASSIGNMENT)])
      if (path.startsWith('/teacher/assignments/')) return Promise.resolve(structuredClone(PROGRESS))
      if (path.includes('/analytics')) return Promise.resolve(structuredClone(EMPTY_ANALYTICS))
      return Promise.resolve(null)
    })
    render(<TeacherDashboard />)
    await screen.findByText('Rahim')

    const before = apiMock.get.mock.calls.length
    await user.click(screen.getByRole('button', { name: t('baProgress') }))
    expect(apiMock.get).toHaveBeenCalledWith('/teacher/assignments/5/progress')
    expect(await screen.findByText('80%')).toBeInTheDocument()
    expect(screen.getByText(t('baDone'))).toBeInTheDocument()
    expect(screen.getByText(t('baPending'))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: t('baProgress') }))
    expect(screen.queryByText(t('baDone'))).not.toBeInTheDocument()
    // cached: reopening fetches from the progress endpoint again at most once
    const progressCalls = apiMock.get.mock.calls
      .slice(before)
      .filter(([p]) => String(p).startsWith('/teacher/assignments/'))
    expect(progressCalls).toHaveLength(1)
  })
})
